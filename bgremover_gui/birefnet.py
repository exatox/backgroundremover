"""
BiRefNet (general, Swin-L backbone), inference only.

Ported from https://huggingface.co/ZhengPeng7/BiRefNet at commit
e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4 (MIT licence; Swin Transformer parts
(c) Microsoft, MIT licence). Only the configuration that checkpoint uses is
kept, and the transformers / timm / kornia / einops dependencies are replaced
with plain PyTorch, so no downloaded code is ever executed. Module names match
the checkpoint so its state dict loads unchanged.
"""

import json
import struct

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.ops import deform_conv2d

INPUT_SIZE = 1024
LATERAL_CHANNELS = [1536 * 2, 768 * 2, 384 * 2, 192 * 2]  # swin_v1_l, multi-scale input concatenated
CONTEXT_CHANNELS = LATERAL_CHANNELS[1:][::-1][-3:]


# ── Swin Transformer backbone ──────────────────────────────────────────────
class Mlp(nn.Module):
    def __init__(self, in_features, hidden_features):
        super().__init__()
        self.fc1 = nn.Linear(in_features, hidden_features)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden_features, in_features)

    def forward(self, x):
        return self.fc2(self.act(self.fc1(x)))


def window_partition(x, window_size):
    B, H, W, C = x.shape
    x = x.view(B, H // window_size, window_size, W // window_size, window_size, C)
    return x.permute(0, 1, 3, 2, 4, 5).contiguous().view(-1, window_size, window_size, C)


def window_reverse(windows, window_size, H, W):
    B = int(windows.shape[0] / (H * W / window_size / window_size))
    x = windows.view(B, H // window_size, W // window_size, window_size, window_size, -1)
    return x.permute(0, 1, 3, 2, 4, 5).contiguous().view(B, H, W, -1)


class WindowAttention(nn.Module):
    def __init__(self, dim, window_size, num_heads):
        super().__init__()
        self.window_size = window_size
        self.num_heads = num_heads
        self.relative_position_bias_table = nn.Parameter(torch.zeros((2 * window_size - 1) ** 2, num_heads))
        coords = torch.stack(torch.meshgrid([torch.arange(window_size), torch.arange(window_size)], indexing="ij"))
        coords = torch.flatten(coords, 1)
        relative = (coords[:, :, None] - coords[:, None, :]).permute(1, 2, 0).contiguous()
        relative[:, :, 0] += window_size - 1
        relative[:, :, 1] += window_size - 1
        relative[:, :, 0] *= 2 * window_size - 1
        self.register_buffer("relative_position_index", relative.sum(-1))
        self.qkv = nn.Linear(dim, dim * 3)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x, mask=None):
        B_, N, C = x.shape
        q, k, v = self.qkv(x).reshape(B_, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        bias = self.relative_position_bias_table[self.relative_position_index.view(-1)].view(N, N, -1)
        bias = bias.permute(2, 0, 1).unsqueeze(0)  # 1, heads, N, N
        if mask is not None:
            nW = mask.shape[0]
            bias = (bias.unsqueeze(1) + mask.unsqueeze(1).unsqueeze(0)).expand(B_ // nW, -1, -1, -1, -1)
            bias = bias.reshape(B_, self.num_heads, N, N)
        # Same maths as softmax(q·kᵀ/√d + bias)·v, using PyTorch's memory-efficient kernel.
        x = F.scaled_dot_product_attention(q, k, v, attn_mask=bias.to(q.dtype))
        return self.proj(x.transpose(1, 2).reshape(B_, N, C))


class SwinTransformerBlock(nn.Module):
    def __init__(self, dim, num_heads, window_size, shift_size):
        super().__init__()
        self.window_size = window_size
        self.shift_size = shift_size
        self.norm1 = nn.LayerNorm(dim)
        self.attn = WindowAttention(dim, window_size, num_heads)
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = Mlp(dim, dim * 4)
        self.H = self.W = None

    def forward(self, x, mask_matrix):
        B, L, C = x.shape
        H, W = self.H, self.W
        shortcut = x
        x = self.norm1(x).view(B, H, W, C)
        pad_r = (self.window_size - W % self.window_size) % self.window_size
        pad_b = (self.window_size - H % self.window_size) % self.window_size
        x = F.pad(x, (0, 0, 0, pad_r, 0, pad_b))
        _, Hp, Wp, _ = x.shape
        if self.shift_size > 0:
            x = torch.roll(x, shifts=(-self.shift_size, -self.shift_size), dims=(1, 2))
            attn_mask = mask_matrix
        else:
            attn_mask = None
        windows = window_partition(x, self.window_size).view(-1, self.window_size * self.window_size, C)
        windows = self.attn(windows, mask=attn_mask).view(-1, self.window_size, self.window_size, C)
        x = window_reverse(windows, self.window_size, Hp, Wp)
        if self.shift_size > 0:
            x = torch.roll(x, shifts=(self.shift_size, self.shift_size), dims=(1, 2))
        if pad_r or pad_b:
            x = x[:, :H, :W, :].contiguous()
        x = shortcut + x.view(B, H * W, C)
        return x + self.mlp(self.norm2(x))


class PatchMerging(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.reduction = nn.Linear(4 * dim, 2 * dim, bias=False)
        self.norm = nn.LayerNorm(4 * dim)

    def forward(self, x, H, W):
        B, L, C = x.shape
        x = x.view(B, H, W, C)
        if H % 2 or W % 2:
            x = F.pad(x, (0, 0, 0, W % 2, 0, H % 2))
        x = torch.cat([x[:, 0::2, 0::2], x[:, 1::2, 0::2], x[:, 0::2, 1::2], x[:, 1::2, 1::2]], -1)
        return self.reduction(self.norm(x.view(B, -1, 4 * C)))


class BasicLayer(nn.Module):
    def __init__(self, dim, depth, num_heads, window_size, downsample):
        super().__init__()
        self.window_size = window_size
        self.shift_size = window_size // 2
        self.blocks = nn.ModuleList([
            SwinTransformerBlock(dim, num_heads, window_size, 0 if i % 2 == 0 else window_size // 2)
            for i in range(depth)
        ])
        self.downsample = PatchMerging(dim) if downsample else None

    def forward(self, x, H, W):
        ws, ss = self.window_size, self.shift_size
        Hp, Wp = -(-H // ws) * ws, -(-W // ws) * ws
        img_mask = torch.zeros((1, Hp, Wp, 1), device=x.device)
        count = 0
        for h in (slice(0, -ws), slice(-ws, -ss), slice(-ss, None)):
            for w in (slice(0, -ws), slice(-ws, -ss), slice(-ss, None)):
                img_mask[:, h, w, :] = count
                count += 1
        mask_windows = window_partition(img_mask, ws).view(-1, ws * ws)
        attn_mask = mask_windows.unsqueeze(1) - mask_windows.unsqueeze(2)
        attn_mask = attn_mask.masked_fill(attn_mask != 0, -100.0).masked_fill(attn_mask == 0, 0.0).to(x.dtype)
        for block in self.blocks:
            block.H, block.W = H, W
            x = block(x, attn_mask)
        if self.downsample is not None:
            return x, H, W, self.downsample(x, H, W), (H + 1) // 2, (W + 1) // 2
        return x, H, W, x, H, W


class PatchEmbed(nn.Module):
    def __init__(self, embed_dim):
        super().__init__()
        self.embed_dim = embed_dim
        self.proj = nn.Conv2d(3, embed_dim, kernel_size=4, stride=4)
        self.norm = nn.LayerNorm(embed_dim)

    def forward(self, x):
        _, _, H, W = x.size()
        if W % 4:
            x = F.pad(x, (0, 4 - W % 4))
        if H % 4:
            x = F.pad(x, (0, 0, 0, 4 - H % 4))
        x = self.proj(x)
        Wh, Ww = x.size(2), x.size(3)
        x = self.norm(x.flatten(2).transpose(1, 2))
        return x.transpose(1, 2).view(-1, self.embed_dim, Wh, Ww)


class SwinTransformer(nn.Module):
    """swin_v1_l: embed_dim 192, depths (2, 2, 18, 2), heads (6, 12, 24, 48), window 12."""

    def __init__(self, embed_dim=192, depths=(2, 2, 18, 2), num_heads=(6, 12, 24, 48), window_size=12):
        super().__init__()
        self.patch_embed = PatchEmbed(embed_dim)
        self.layers = nn.ModuleList([
            BasicLayer(embed_dim * 2 ** i, depths[i], num_heads[i], window_size, downsample=i < len(depths) - 1)
            for i in range(len(depths))
        ])
        self.num_features = [embed_dim * 2 ** i for i in range(len(depths))]
        for i, features in enumerate(self.num_features):
            self.add_module(f"norm{i}", nn.LayerNorm(features))

    def forward(self, x):
        x = self.patch_embed(x)
        Wh, Ww = x.size(2), x.size(3)
        x = x.flatten(2).transpose(1, 2)
        outs = []
        for i, layer in enumerate(self.layers):
            x_out, H, W, x, Wh, Ww = layer(x, Wh, Ww)
            x_out = getattr(self, f"norm{i}")(x_out)
            outs.append(x_out.view(-1, H, W, self.num_features[i]).permute(0, 3, 1, 2).contiguous())
        return tuple(outs)


# ── decoder ────────────────────────────────────────────────────────────────
class DeformableConv2d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, padding):
        super().__init__()
        self.padding = padding
        self.offset_conv = nn.Conv2d(in_channels, 2 * kernel_size * kernel_size, kernel_size, 1, padding)
        self.modulator_conv = nn.Conv2d(in_channels, kernel_size * kernel_size, kernel_size, 1, padding)
        self.regular_conv = nn.Conv2d(in_channels, out_channels, kernel_size, 1, padding, bias=False)

    def forward(self, x):
        return deform_conv2d(
            input=x,
            offset=self.offset_conv(x),
            weight=self.regular_conv.weight,
            bias=self.regular_conv.bias,
            padding=self.padding,
            mask=2.0 * torch.sigmoid(self.modulator_conv(x)),
            stride=(1, 1),
        )


class _ASPPModuleDeformable(nn.Module):
    def __init__(self, in_channels, planes, kernel_size, padding):
        super().__init__()
        self.atrous_conv = DeformableConv2d(in_channels, planes, kernel_size, padding)
        self.bn = nn.BatchNorm2d(planes)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.relu(self.bn(self.atrous_conv(x)))


class ASPPDeformable(nn.Module):
    def __init__(self, in_channels, block_sizes=(1, 3, 7)):
        super().__init__()
        inter = 256
        self.aspp1 = _ASPPModuleDeformable(in_channels, inter, 1, 0)
        self.aspp_deforms = nn.ModuleList([_ASPPModuleDeformable(in_channels, inter, k, k // 2) for k in block_sizes])
        self.global_avg_pool = nn.Sequential(
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Conv2d(in_channels, inter, 1, bias=False),
            nn.BatchNorm2d(inter),
            nn.ReLU(inplace=True),
        )
        self.conv1 = nn.Conv2d(inter * (2 + len(block_sizes)), in_channels, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(in_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x1 = self.aspp1(x)
        pooled = F.interpolate(self.global_avg_pool(x), size=x1.shape[2:], mode="bilinear", align_corners=True)
        x = torch.cat((x1, *[block(x) for block in self.aspp_deforms], pooled), dim=1)
        return self.relu(self.bn1(self.conv1(x)))


class BasicDecBlk(nn.Module):
    def __init__(self, in_channels, out_channels, inter_channels=64):
        super().__init__()
        self.conv_in = nn.Conv2d(in_channels, inter_channels, 3, 1, padding=1)
        self.bn_in = nn.BatchNorm2d(inter_channels)
        self.relu_in = nn.ReLU(inplace=True)
        self.dec_att = ASPPDeformable(inter_channels)
        self.conv_out = nn.Conv2d(inter_channels, out_channels, 3, 1, padding=1)
        self.bn_out = nn.BatchNorm2d(out_channels)

    def forward(self, x):
        x = self.relu_in(self.bn_in(self.conv_in(x)))
        return self.bn_out(self.conv_out(self.dec_att(x)))


class BasicLatBlk(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, 1, 1, 0)

    def forward(self, x):
        return self.conv(x)


class SimpleConvs(nn.Module):
    def __init__(self, in_channels, out_channels, inter_channels=64):
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, inter_channels, 3, 1, 1)
        self.conv_out = nn.Conv2d(inter_channels, out_channels, 3, 1, 1)

    def forward(self, x):
        return self.conv_out(self.conv1(x))


def image2patches(image, ref):
    """einops 'b c (hg h) (wg w) -> b (c hg wg) h w', with the grid taken from ref's size."""
    b, c, H, W = image.shape
    hg, wg = H // ref.shape[-2], W // ref.shape[-1]
    h, w = H // hg, W // wg
    return image.view(b, c, hg, h, wg, w).permute(0, 1, 2, 4, 3, 5).reshape(b, c * hg * wg, h, w)


def _gdt_convs(channels):
    return nn.Sequential(nn.Conv2d(channels, 16, 3, 1, 1), nn.BatchNorm2d(16), nn.ReLU(inplace=True))


class Decoder(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.ipt_blk5 = SimpleConvs(2 ** 10 * 3, channels[0] // 8)
        self.ipt_blk4 = SimpleConvs(2 ** 8 * 3, channels[0] // 8)
        self.ipt_blk3 = SimpleConvs(2 ** 6 * 3, channels[1] // 8)
        self.ipt_blk2 = SimpleConvs(2 ** 4 * 3, channels[2] // 8)
        self.ipt_blk1 = SimpleConvs(2 ** 0 * 3, channels[3] // 8)

        self.decoder_block4 = BasicDecBlk(channels[0] + channels[0] // 8, channels[1])
        self.decoder_block3 = BasicDecBlk(channels[1] + channels[0] // 8, channels[2])
        self.decoder_block2 = BasicDecBlk(channels[2] + channels[1] // 8, channels[3])
        self.decoder_block1 = BasicDecBlk(channels[3] + channels[2] // 8, channels[3] // 2)
        self.conv_out1 = nn.Sequential(nn.Conv2d(channels[3] // 2 + channels[3] // 8, 1, 1, 1, 0))

        self.lateral_block4 = BasicLatBlk(channels[1], channels[1])
        self.lateral_block3 = BasicLatBlk(channels[2], channels[2])
        self.lateral_block2 = BasicLatBlk(channels[3], channels[3])

        # Deep-supervision heads: only used in training, kept so the checkpoint loads strictly.
        self.conv_ms_spvn_4 = nn.Conv2d(channels[1], 1, 1, 1, 0)
        self.conv_ms_spvn_3 = nn.Conv2d(channels[2], 1, 1, 1, 0)
        self.conv_ms_spvn_2 = nn.Conv2d(channels[3], 1, 1, 1, 0)

        self.gdt_convs_4 = _gdt_convs(channels[1])
        self.gdt_convs_3 = _gdt_convs(channels[2])
        self.gdt_convs_2 = _gdt_convs(channels[3])
        self.gdt_convs_pred_4 = nn.Sequential(nn.Conv2d(16, 1, 1, 1, 0))
        self.gdt_convs_pred_3 = nn.Sequential(nn.Conv2d(16, 1, 1, 1, 0))
        self.gdt_convs_pred_2 = nn.Sequential(nn.Conv2d(16, 1, 1, 1, 0))
        self.gdt_convs_attn_4 = nn.Sequential(nn.Conv2d(16, 1, 1, 1, 0))
        self.gdt_convs_attn_3 = nn.Sequential(nn.Conv2d(16, 1, 1, 1, 0))
        self.gdt_convs_attn_2 = nn.Sequential(nn.Conv2d(16, 1, 1, 1, 0))

    @staticmethod
    def _with_input(feature, x, block):
        patches = F.interpolate(image2patches(x, feature), size=feature.shape[2:], mode="bilinear", align_corners=True)
        return torch.cat((feature, block(patches)), 1)

    def forward(self, features):
        x, x1, x2, x3, x4 = features
        x4 = self._with_input(x4, x, self.ipt_blk5)
        p4 = self.decoder_block4(x4)
        p4 = p4 * self.gdt_convs_attn_4(self.gdt_convs_4(p4)).sigmoid()
        _p3 = F.interpolate(p4, size=x3.shape[2:], mode="bilinear", align_corners=True) + self.lateral_block4(x3)

        _p3 = self._with_input(_p3, x, self.ipt_blk4)
        p3 = self.decoder_block3(_p3)
        p3 = p3 * self.gdt_convs_attn_3(self.gdt_convs_3(p3)).sigmoid()
        _p2 = F.interpolate(p3, size=x2.shape[2:], mode="bilinear", align_corners=True) + self.lateral_block3(x2)

        _p2 = self._with_input(_p2, x, self.ipt_blk3)
        p2 = self.decoder_block2(_p2)
        p2 = p2 * self.gdt_convs_attn_2(self.gdt_convs_2(p2)).sigmoid()
        _p1 = F.interpolate(p2, size=x1.shape[2:], mode="bilinear", align_corners=True) + self.lateral_block2(x1)

        _p1 = self._with_input(_p1, x, self.ipt_blk2)
        _p1 = self.decoder_block1(_p1)
        _p1 = F.interpolate(_p1, size=x.shape[2:], mode="bilinear", align_corners=True)
        _p1 = self._with_input(_p1, x, self.ipt_blk1)
        return self.conv_out1(_p1)


class BiRefNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.bb = SwinTransformer()
        channels = LATERAL_CHANNELS
        self.squeeze_module = nn.Sequential(BasicDecBlk(channels[0] + sum(CONTEXT_CHANNELS), channels[0]))
        self.decoder = Decoder(channels)

    def forward(self, x):
        """x: (B, 3, 1024, 1024) normalised RGB. Returns mask logits (B, 1, 1024, 1024)."""
        x1, x2, x3, x4 = self.bb(x)
        H, W = x.shape[2:]
        half = self.bb(F.interpolate(x, size=(H // 2, W // 2), mode="bilinear", align_corners=True))
        x1, x2, x3, x4 = [
            torch.cat([full, F.interpolate(small, size=full.shape[2:], mode="bilinear", align_corners=True)], dim=1)
            for full, small in zip((x1, x2, x3, x4), half)
        ]
        x4 = torch.cat(
            [F.interpolate(t, size=x4.shape[2:], mode="bilinear", align_corners=True) for t in (x1, x2, x3)] + [x4],
            dim=1,
        )
        x4 = self.squeeze_module(x4)
        return self.decoder([x, x1, x2, x3, x4])


# ── weights ────────────────────────────────────────────────────────────────
_DTYPES = {"F32": torch.float32, "F16": torch.float16, "BF16": torch.bfloat16, "I64": torch.int64, "F64": torch.float64}


def load_safetensors(path):
    """Read a .safetensors file (JSON header + raw little-endian tensors). Pure data: nothing is executed."""
    with open(path, "rb") as f:
        header_len = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(header_len))
        data = f.read()
    tensors = {}
    for name, spec in header.items():
        if name == "__metadata__":
            continue
        start, end = spec["data_offsets"]
        raw = np.frombuffer(data, dtype=np.uint8, count=end - start, offset=start).copy()
        tensors[name] = torch.from_numpy(raw).view(_DTYPES[spec["dtype"]]).reshape(spec["shape"])
    return tensors


def build(weights_path):
    net = BiRefNet()
    state = load_safetensors(weights_path)
    net.load_state_dict({k: v.float() if v.is_floating_point() else v for k, v in state.items()})
    return net.eval()
