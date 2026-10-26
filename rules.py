# -*- coding: utf-8 -*-
"""清理规则表。

设计原则：
1. **声明式**——规则是数据，不是散落在代码里的 if 分支；
2. **分层**——按「删掉会不会丢东西 / 会不会让系统变慢」分三级；
3. **不写死用户名**——路径用 %LOCALAPPDATA% 之类的环境变量，换台机器照样能用。

刻意不在这里的：回收站、文档、桌面、图片、视频、任何项目目录。
那些是用户数据，不该由清理工具代劳。
"""
import os
from dataclasses import dataclass
from enum import Enum


class Level(str, Enum):
    """安全等级。值越大越危险。"""

    SAFE = "safe"        # 纯缓存，删了立刻重新生成，无副作用
    CAUTION = "caution"  # 系统/驱动缓存，删了会重新生成但可能暂时变慢
    RISKY = "risky"      # 需要停服务或影响系统更新，默认不碰

    @property
    def order(self) -> int:
        return {"safe": 1, "caution": 2, "risky": 3}[self.value]


@dataclass(frozen=True)
class Rule:
    key: str
    name: str
    path: str
    level: Level
    note: str = ""
    patterns: tuple = ()   # 非空时只清理匹配这些 glob 的文件，保留目录其余内容

    @property
    def expanded(self) -> str:
        return expand(self.path)

    @property
    def is_filtered(self) -> bool:
        return bool(self.patterns)


def expand(path: str) -> str:
    """展开 %VAR% 并解析为真实路径。

    必须走 realpath：%TEMP% 常展开成 `C:\\Users\\LESLIE~1\\...` 这类 8.3 短名，
    而 %LOCALAPPDATA%\\Temp 是长名，两者指向同一目录却字符串不等，
    不去重就会把同一个 Temp 目录统计两遍。
    展开失败的变量原样保留，便于报错时定位。
    """
    p = os.path.expandvars(path)
    if "%" in p:          # 有变量没展开成功
        return os.path.normpath(p)
    return os.path.realpath(p)


RULES = [
    # ---------------- SAFE：纯缓存 ----------------
    Rule("user_temp", "用户临时文件", r"%LOCALAPPDATA%\Temp", Level.SAFE,
         "安装包解压残留、程序临时文件"),
    Rule("win_temp_user", "系统临时文件（当前用户）", r"%TEMP%", Level.SAFE,
         "通常与 %LOCALAPPDATA%\\Temp 指向同一目录"),
    Rule("edge_cache", "Edge 网页缓存", r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache", Level.SAFE,
         "网页图片与脚本缓存"),
    Rule("edge_codecache", "Edge 代码缓存", r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Code Cache", Level.SAFE,
         "编译后的 JS 缓存"),
    Rule("edge_gpu", "Edge GPU 缓存", r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\GPUCache", Level.SAFE,
         "着色器与 GPU 中间产物"),
    Rule("chrome_cache", "Chrome 网页缓存", r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache", Level.SAFE,
         "网页图片与脚本缓存"),
    Rule("chrome_codecache", "Chrome 代码缓存", r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Code Cache", Level.SAFE,
         "编译后的 JS 缓存"),
    Rule("chrome_gpu", "Chrome GPU 缓存", r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\GPUCache", Level.SAFE,
         "着色器与 GPU 中间产物"),
    Rule("npm_cache", "npm 缓存", r"%LOCALAPPDATA%\npm-cache", Level.SAFE,
         "已下载的包，重装会重新拉取"),
    Rule("pip_cache", "pip 缓存", r"%LOCALAPPDATA%\pip\cache", Level.SAFE,
         "wheel 与源码包缓存"),
    Rule("crashdumps", "崩溃转储", r"%LOCALAPPDATA%\CrashDumps", Level.SAFE,
         "程序崩溃时的内存快照，一般不用于日常排查"),
    Rule("thumbcache", "资源管理器缩略图缓存", r"%LOCALAPPDATA%\Microsoft\Windows\Explorer", Level.SAFE,
         "只清 thumbcache_*.db 与 iconcache_*.db；该目录还存着窗口布局等设置，不能整个删",
         patterns=("thumbcache_*.db", "iconcache_*.db")),

    # ---------------- CAUTION：会重新生成，但可能暂时变慢 ----------------
    Rule("nv_dxcache", "NVIDIA 着色器缓存（DX）", r"%LOCALAPPDATA%\NVIDIA\DXCache", Level.CAUTION,
         "删后游戏/建模软件首次加载会重新编译着色器，变慢一阵"),
    Rule("nv_glcache", "NVIDIA 着色器缓存（GL）", r"%LOCALAPPDATA%\NVIDIA\GLCache", Level.CAUTION,
         "同上，OpenGL 部分"),
    Rule("d3dscache", "DirectX 着色器缓存", r"%LOCALAPPDATA%\D3DSCache", Level.CAUTION,
         "同 NVIDIA 缓存性质"),
    Rule("prefetch", "预读取数据", r"%WINDIR%\Prefetch", Level.CAUTION,
         "删除后常用程序启动会略慢，几天内自动重建"),

    # ---------------- RISKY：涉及系统服务 ----------------
    Rule("win_temp", "Windows 临时目录", r"%WINDIR%\Temp", Level.RISKY,
         "可能有正在被服务占用的文件，删除时会自动跳过"),
    Rule("win_logs", "Windows 日志", r"%WINDIR%\Logs", Level.RISKY,
         "排障时有用，非必要不建议清"),
    Rule("wu_download", "Windows 更新下载缓存", r"%WINDIR%\SoftwareDistribution\Download", Level.RISKY,
         "需先停止 wuauserv 服务，否则多数文件被占用；工具不会替你停服务"),
]

# 明确不处理、并在 README 里说明原因的目标
NOT_TOUCHED = [
    ("回收站（$Recycle.Bin）", "里面是你删过的文件，清理工具无权替你决定永久丢弃"),
    ("文档 / 桌面 / 图片 / 视频", "用户数据，不属于缓存"),
    ("node_modules / .git / venv", "项目工作区，删了要重新装或丢失历史"),
    ("SoftwareDistribution 以外的 Windows 目录", "系统组件，误删代价过高"),
]

# 大文件报告关注的扩展名分类
BIG_FILE_KINDS = {
    "视频": {".mp4", ".mkv", ".mov", ".avi", ".flv", ".ts", ".webm", ".m4v", ".wmv"},
    "镜像/安装包": {".iso", ".img", ".msi", ".exe", ".zip", ".7z", ".rar", ".tar", ".gz"},
    "模型/权重": {".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".bin"},
    "虚拟机/备份": {".vmdk", ".vdi", ".vhdx", ".bak", ".bsdiff"},
    "音频": {".flac", ".wav", ".ape", ".m4a"},
}


def kind_of(path: str) -> str:
    """按扩展名归类，识别不了返回「其他」。"""
    ext = os.path.splitext(path)[1].lower()
    for name, exts in BIG_FILE_KINDS.items():
        if ext in exts:
            return name
    return "其他"


def rules_up_to(level: Level):
    """返回等级不超过 level 的规则（含本级）。"""
    return [r for r in RULES if r.level.order <= level.order]


def existing_rules(level: Level):
    """筛选出路径真实存在的规则，返回 (rule, 实际路径) 列表。"""
    out, seen = [], set()
    for r in rules_up_to(level):
        p = r.expanded
        if "%" in p:          # 变量没展开成功
            continue
        if not os.path.isdir(p):
            continue
        key = p.lower()
        if key in seen:       # %TEMP% 与 %LOCALAPPDATA%\Temp 常指向同一处
            continue
        seen.add(key)
        out.append((r, p))
    return out
