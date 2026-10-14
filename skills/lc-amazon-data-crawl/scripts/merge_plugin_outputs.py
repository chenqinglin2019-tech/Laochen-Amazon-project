"""Rebuild/merge committed native exports locally, without browser operations."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from run_outcome import CrawlStop, _atomic_write_json
from sellersprite_export import write_outputs


def collect_committed(job_dirs):
    records, sources = [], []
    seen = set()
    for job in job_dirs:
        state = json.loads((Path(job)/'state.json').read_text(encoding='utf-8'))
        for task in state['tasks'].values():
            # Never glob raw_exports: intermediate and failed downloads stay excluded.
            if not task.get('raw_file'):
                continue
            path = str(Path(task['raw_file']).resolve())
            if path in seen:
                continue
            seen.add(path)
            sources.append({k: v for k, v in task.items() if k != 'records'})
            records.extend(task.get('records', []))
    return records, sources


def main():
    parser = argparse.ArgumentParser(description='按原始下载格式重建或跨任务合并店铺/关键词结果，不重采。')
    parser.add_argument('--job-dir', action='append', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--config', type=Path, help='沿用此配置的本地筛选规则；省略则不过滤、不排除广告')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    command = (['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(root/'scripts/check_auth.ps1')]
               if os.name == 'nt' else ['bash', str(root/'scripts/check_auth.sh')])
    status = subprocess.run(command, cwd=root).returncode
    if status:
        return status
    try:
        records, sources = collect_committed(args.job_dir)
        config = json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
        args.output_dir.mkdir(parents=True, exist_ok=True)
        quality = write_outputs(args.output_dir, records, sources, config.get('product_filters', {}),
                                config.get('include_sponsored', True))
        _atomic_write_json(args.output_dir/'quality_report.json', quality)
        print(json.dumps(quality['native_workbook'], ensure_ascii=False))
        return 0
    except CrawlStop as exc:
        print(str(exc))
        return exc.exit_code
    except (OSError, ValueError, KeyError) as exc:
        print(f'无法读取任务断点或配置：{exc}')
        return 40


if __name__ == '__main__':
    raise SystemExit(main())
