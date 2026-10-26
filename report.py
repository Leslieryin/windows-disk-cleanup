# -*- coding: utf-8 -*-
"""大小统计与 Markdown 报告渲染。

本模块只读文件系统，不做任何删除/移动。
"""
import fnmatch
import os
import shutil
from datetime import datetime


def human(n) -> str:
    """字节数转人类可读。用 1024 进制，与资源管理器口径一致。"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            if unit == "B":
                return "%d B" % int(n)
            return "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f PB" % n


def walk_stats(root, patterns=()):
    """统计目录下的文件数与总字节。

    patterns 非空时只统计文件名匹配任一 glob 的文件（用于 thumbcache 这类
    目录里只有部分文件该清的规则）。
    返回 (文件数, 总字节)。
    """
    files, total = 0, 0
    for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda e: None):
        for name in filenames:
            if patterns and not any(fnmatch.fnmatch(name, p) for p in patterns):
                continue
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
                files += 1
            except OSError:
                continue
    return files, total


def disk_usage(path):
    """返回 (total, used, free) 字节；失败返回 None。"""
    try:
        return shutil.disk_usage(path)
    except OSError:
        return None


def _table(headers, rows, aligns=None):
    """渲染 Markdown 表格。aligns 取值 l/r/c。"""
    aligns = aligns or ["l"] * len(headers)
    mark = {"l": ":---", "r": "---:", "c": ":---:"}
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(mark[a] for a in aligns) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _header(title, subtitle=None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["# " + title, "", "> 生成时间：%s" % ts]
    if subtitle:
        lines.append("> " + subtitle)
    return "\n".join(lines) + "\n"


def render_scan(rows, disk, level, drive=None):
    """rows: [(rule, path, files, bytes)]"""
    total_bytes = sum(r[3] for r in rows)
    total_files = sum(r[2] for r in rows)

    parts = [_header("磁盘清理扫描报告",
                     "等级 ≤ **%s**，共命中 %d 个位置 / %d 个文件 / 合计 **%s**"
                     % (level.value, len(rows), total_files, human(total_bytes)))]

    if disk:
        total, used, free = disk
        parts.append("磁盘 `%s`：总容量 %s，已用 %s，剩余 **%s**（%.1f%% 可用）\n"
                     % (drive or "", human(total), human(used), human(free),
                        free / total * 100 if total else 0))

    parts.append("## 明细\n")
    table_rows = []
    for rule, path, files, size in sorted(rows, key=lambda x: -x[3]):
        table_rows.append([
            "`%s`" % rule.level.value,
            rule.name,
            "%d" % files,
            human(size),
            "<br>".join(filter(None, ["`%s`" % path, rule.note])),
        ])
    parts.append(_table(["等级", "项目", "文件数", "大小", "路径与说明"], table_rows,
                        ["c", "l", "r", "r", "l"]))

    parts.append("""
## 下一步

```bash
python cleanup.py clean --level safe              # 只清安全级，先跑加 --dry-run 预演
python cleanup.py clean --level caution           # 加上驱动/预读取缓存
python cleanup.py clean --level risky --yes       # 系统缓存，需显式确认
```

等级含义见 README「安全模型」一节。
""")
    return "\n".join(parts)


def render_clean(results, freed_bytes, failed, disk, drive=None):
    """results: [(rule, path, deleted_files, skipped_files, freed_bytes)]"""
    total_del = sum(r[2] for r in results)
    total_skip = sum(r[3] for r in results)

    parts = [_header("磁盘清理执行报告",
                     "删除 %d 个文件，跳过 %d 个（占用中/无权限），释放 **%s**"
                     % (total_del, total_skip, human(freed_bytes)))]

    if disk:
        total, used, free = disk
        parts.append("磁盘 `%s`：剩余 **%s** / %s\n"
                     % (drive or "", human(free), human(total)))

    table_rows = [[r[0].name, "%d" % r[2], "%d" % r[3], human(r[4])] for r in results]
    parts.append("## 明细\n")
    parts.append(_table(["项目", "已删", "跳过", "释放"], table_rows, ["l", "r", "r", "r"]))

    if failed:
        parts.append("\n## 无法删除的样本\n")
        parts.append("以下文件被占用或权限不足，已自动跳过，不影响其他文件：\n")
        for p, err in failed[:15]:
            parts.append("- `%s` — %s" % (p, err))
    return "\n".join(parts)


def render_bigfiles(items, root, threshold, top):
    """items: [(path, size, kind)]"""
    total = sum(i[1] for i in items)
    parts = [_header("大文件报告",
                     "扫描 `%s`，阈值 %s，命中 %d 个，合计 **%s**"
                     % (root, human(threshold), len(items), human(total))),
             "本报告只列出，不删除任何文件。请自行判断哪些可以移走或删除。\n"]

    rows = []
    for i, (path, size, kind) in enumerate(items[:top], 1):
        rows.append([i, human(size), kind, "`%s`" % path])
    parts.append(_table(["#", "大小", "类型", "路径"], rows, ["r", "r", "l", "l"]))
    return "\n".join(parts)


def render_media(buckets, root, years, total_bytes):
    """buckets: {年份: (文件数, 字节)}，按年聚合"""
    parts = [_header("旧媒体占用报告",
                     "扫描 `%s`，早于 %d 年前的内容合计 **%s**"
                     % (root, years, human(total_bytes)))]

    if not buckets:
        parts.append("\n没有找到媒体文件。")
        return "\n".join(parts)

    rows = []
    for year in sorted(buckets):
        cnt, size = buckets[year]
        rows.append([year, cnt, human(size)])
    parts.append("## 按年份\n")
    parts.append(_table(["年份", "文件数", "占用"], rows, ["c", "r", "r"]))

    parts.append("""
## 说明

本报告**不删除任何文件**。清理旧媒体的风险远高于清缓存：

- 视频和照片往往没有副本，删了就是没了
- 年份按文件名日期优先、修改时间兜底，可能有误判
- 建议先按年份人工看一遍，用资源管理器或 `media --list` 导出清单后再决定
""")
    return "\n".join(p for p in parts if p)
