#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 磁盘清理 —— 分层、可预演、默认只读。

    python cleanup.py scan                        # 扫描并出报告（默认，不删任何东西）
    python cleanup.py clean --level safe          # 清理安全级（缓存类）
    python cleanup.py clean --level safe --dry-run
    python cleanup.py bigfiles --top 30           # 大文件报告，只列不删
    python cleanup.py media --older-than-years 2  # 旧媒体占用报告，只列不删

只清可再生的缓存。回收站、文档、照片、项目目录一律不碰——理由见 README。
"""
import argparse
import fnmatch
import os
import sys
import time

import report
import rules as R

REPORT_DIR = "cleanup-reports"

# 允许作为清理目标的顶层目录。规则里的路径必须落在其中之一，
# 这样即使规则表被改坏，也不会指到用户数据上。
def allowed_roots():
    """允许作为清理目标的顶层目录。

    刻意不含 %USERPROFILE%：主目录下还有文档、桌面、图片、代码，
    只放行挂载在其下的具体缓存根（LOCALAPPDATA / APPDATA / TEMP）与系统缓存根。
    """
    roots = []
    for var in ("LOCALAPPDATA", "APPDATA", "TEMP", "WINDIR", "PROGRAMDATA"):
        val = os.environ.get(var)
        if val:
            roots.append(os.path.normcase(os.path.normpath(val)))
    return roots


def guard(path):
    """返回拒绝理由；None 表示可以动手。"""
    norm = os.path.normcase(os.path.normpath(path))
    if ".git" in norm.split(os.sep):
        return "路径含 .git"
    if norm in ("c:\\", "d:\\", "e:\\"):
        return "盘符根目录"
    home = os.path.normcase(os.path.normpath(os.path.expanduser("~")))
    if norm == home:
        return "用户主目录本身"
    roots = allowed_roots()
    if roots and not any(norm == r or norm.startswith(r + os.sep) for r in roots):
        return "不在允许的根目录下"
    return None


def remove_file(path):
    """删除单个文件。成功返回大小，失败抛 OSError。"""
    size = os.lstat(path).st_size
    os.remove(path)
    return size


def clean_one(rule, path, dry_run):
    """清理单个规则目标，返回 (删除数, 跳过数, 释放字节, 错误样本)。"""
    deleted = skipped = freed = 0
    errs = []

    if rule.is_filtered:
        # 只删匹配的文件，目录里其余内容原样保留
        try:
            names = os.listdir(path)
        except OSError:
            return 0, 0, 0, []
        for name in names:
            if not any(fnmatch.fnmatch(name, p) for p in rule.patterns):
                continue
            fp = os.path.join(path, name)
            if not os.path.isfile(fp):
                continue
            try:
                size = os.lstat(fp).st_size if dry_run else remove_file(fp)
                deleted += 1
                freed += size
            except OSError as e:
                skipped += 1
                if len(errs) < 3:
                    errs.append((fp, str(e)))
        return deleted, skipped, freed, errs

    for dirpath, dirnames, filenames in os.walk(path, topdown=False, onerror=lambda e: None):
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                if dry_run:
                    size = os.lstat(fp).st_size
                    deleted += 1
                    freed += size
                else:
                    freed += remove_file(fp)
                    deleted += 1
            except OSError as e:
                skipped += 1
                if len(errs) < 3:
                    errs.append((fp, str(e)))
        if dry_run:
            continue
        for name in dirnames:      # 自底向上顺手清空目录，根目录保留
            try:
                os.rmdir(os.path.join(dirpath, name))
            except OSError:
                pass
    return deleted, skipped, freed, errs


def write_report(text, out, prefix):
    if not out:
        return None
    os.makedirs(out, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(out, "%s-%s.md" % (prefix, stamp))
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    return dest


def cmd_scan(args):
    level = R.Level(args.level)
    targets = R.existing_rules(level)
    if not targets:
        print("没有找到任何存在的清理目标。")
        return 0

    print("%-8s%-24s%10s%12s  %s" % ("等级", "项目", "文件数", "大小", "路径"))
    print("-" * 100)
    rows = []
    for rule, path in targets:
        files, size = report.walk_stats(path, rule.patterns)
        rows.append((rule, path, files, size))
        print("%-8s%-24s%10d%12s  %s"
              % (rule.level.value, rule.name, files, report.human(size), path))

    total = sum(r[3] for r in rows)
    print("-" * 100)
    print("合计 %d 个位置，%d 个文件，%s"
          % (len(rows), sum(r[2] for r in rows), report.human(total)))

    disk = report.disk_usage(os.environ.get("SystemDrive", "C:") + os.sep)
    md = report.render_scan(rows, disk, level, os.environ.get("SystemDrive", "C:"))
    dest = write_report(md, args.out, "scan")
    if dest:
        print("\n报告已写入 %s" % dest)
    print("\n这是一次只读扫描，没有删除任何文件。确认无误后用 clean --level %s 执行。" % level.value)
    return 0


def cmd_clean(args):
    level = R.Level(args.level)
    if level is R.Level.RISKY and not args.yes:
        print("risky 级会动 Windows 临时目录、日志与更新缓存，可能有服务正在使用。")
        print("确认要继续请追加 --yes。")
        return 2

    targets = R.existing_rules(level)
    if not targets:
        print("没有找到任何存在的清理目标。")
        return 0

    results, all_errs = [], []
    t0 = time.time()
    print("%-24s%8s%8s%12s" % ("项目", "已删", "跳过", "释放"))
    print("-" * 60)

    for rule, path in targets:
        reason = guard(path)
        if reason:
            print("%-24s  跳过：%s" % (rule.name, reason))
            continue
        deleted, skipped, freed, errs = clean_one(rule, path, args.dry_run)
        results.append((rule, path, deleted, skipped, freed))
        all_errs.extend(errs)
        print("%-24s%8d%8d%12s" % (rule.name, deleted, skipped, report.human(freed)))

    freed = sum(r[4] for r in results)
    print("-" * 60)
    verb = "可释放" if args.dry_run else "已释放"
    print("%s %s，耗时 %.0fs" % (verb, report.human(freed), time.time() - t0))
    if args.dry_run:
        print("\n[试运行] 未删除任何文件。去掉 --dry-run 执行。")

    disk = report.disk_usage(os.environ.get("SystemDrive", "C:") + os.sep)
    if disk and not args.dry_run:
        print("磁盘剩余 %s / %s" % (report.human(disk[2]), report.human(disk[0])))

    md = report.render_clean(results, freed, all_errs, disk, os.environ.get("SystemDrive", "C:"))
    dest = write_report(md, args.out, "clean")
    if dest:
        print("报告已写入 %s" % dest)
    return 0


def cmd_bigfiles(args):
    root = os.path.abspath(args.root or os.path.expanduser("~"))
    threshold = int(args.min_mb * 1024 * 1024)
    skip = {"$recycle.bin", "node_modules", ".git", "appdata", "cleanup-reports"}
    items = []

    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d.lower() not in skip]
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                size = os.lstat(fp).st_size
            except OSError:
                continue
            if size >= threshold:
                items.append((fp, size, R.kind_of(fp)))

    items.sort(key=lambda x: -x[1])
    total = sum(i[1] for i in items)
    print("扫描 %s，阈值 %s，命中 %d 个文件，合计 %s\n"
          % (root, report.human(threshold), len(items), report.human(total)))
    print("%4s%12s  %-10s%s" % ("#", "大小", "类型", "路径"))
    print("-" * 100)
    for i, (fp, size, kind) in enumerate(items[:args.top], 1):
        print("%4d%12s  %-10s%s" % (i, report.human(size), kind, fp))

    md = report.render_bigfiles(items, root, threshold, args.top)
    dest = write_report(md, args.out, "bigfiles")
    if dest:
        print("\n报告已写入 %s" % dest)
    print("只列出，未删除任何文件。")
    return 0


def cmd_media(args):
    root = os.path.abspath(args.root or os.path.expanduser("~"))
    from datetime import datetime

    media_ext = set()
    for name in ("视频", "音频"):
        media_ext |= R.BIG_FILE_KINDS[name]
    media_ext |= {".jpg", ".jpeg", ".png", ".heic", ".gif", ".bmp", ".webp"}

    cutoff_year = datetime.now().year - args.older_than_years
    buckets = {}
    old_total = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d.lower() not in ("node_modules", ".git")]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in media_ext:
                continue
            fp = os.path.join(dirpath, name)
            try:
                year = datetime.fromtimestamp(os.path.getmtime(fp)).year
                size = os.lstat(fp).st_size
            except OSError:
                continue
            cnt, s = buckets.get(year, (0, 0))
            buckets[year] = (cnt + 1, s + size)
            if year < cutoff_year:
                old_total += size

    print("按年份统计（年份取修改时间）：\n")
    print("%6s%10s%12s" % ("年份", "文件数", "占用"))
    print("-" * 30)
    for year in sorted(buckets):
        cnt, size = buckets[year]
        flag = "  <- 早于 %d" % cutoff_year if year < cutoff_year else ""
        print("%6d%10d%12s%s" % (year, cnt, report.human(size), flag))
    print("-" * 30)
    print("早于 %d 年的媒体合计 %s" % (cutoff_year, report.human(old_total)))

    md = report.render_media(buckets, root, args.older_than_years, old_total)
    dest = write_report(md, args.out, "media")
    if dest:
        print("\n报告已写入 %s" % dest)
    print("\n只统计，未删除任何文件。媒体文件通常没有副本，建议人工确认后再手动处理。")
    return 0


def main():
    ap = argparse.ArgumentParser(
        prog="cleanup.py",
        description="Windows 磁盘清理：分层、可预演、默认只读",
        epilog="只清可再生的缓存，不碰回收站与用户数据。",
    )
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="扫描清理目标并出报告（默认命令，只读）")
    s.add_argument("--level", default="risky", choices=["safe", "caution", "risky"],
                   help="扫描到哪个等级，默认全部")
    s.add_argument("--out", default=REPORT_DIR, help="报告输出目录，默认 %s" % REPORT_DIR)
    s.set_defaults(func=cmd_scan)

    c = sub.add_parser("clean", help="执行清理")
    c.add_argument("--level", default="safe", choices=["safe", "caution", "risky"])
    c.add_argument("--dry-run", action="store_true", help="只统计不删除")
    c.add_argument("--yes", action="store_true", help="risky 级需要显式确认")
    c.add_argument("--out", default=REPORT_DIR, help="报告输出目录")
    c.set_defaults(func=cmd_clean)

    b = sub.add_parser("bigfiles", help="大文件报告，只列不删")
    b.add_argument("--root", default=None, help="扫描根目录，默认用户主目录")
    b.add_argument("--min-mb", type=float, default=500, help="大小阈值（MB），默认 500")
    b.add_argument("--top", type=int, default=30, help="列出前 N 个，默认 30")
    b.add_argument("--out", default=REPORT_DIR)
    b.set_defaults(func=cmd_bigfiles)

    m = sub.add_parser("media", help="旧媒体占用报告，只统计不删")
    m.add_argument("--root", default=None, help="扫描根目录，默认用户主目录")
    m.add_argument("--older-than-years", type=int, default=2, help="判定「旧」的年数，默认 2")
    m.add_argument("--out", default=REPORT_DIR)
    m.set_defaults(func=cmd_media)

    args = ap.parse_args()
    if not args.cmd:
        args = ap.parse_args(["scan"])
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
