#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
disk_usage_visualizer.py

Windows Server 2019 / Python 3.7+ 標準モジュールのみで動作。
指定したパス（既定: D:\）以下のフォルダ・ファイル容量を再帰的に集計し、
外部ライブラリ・インターネット接続不要でブラウザで開ける単体 HTML を出力する。

使い方例:
    python disk_usage_visualizer.py --path D:\ --depth 3 --output d_usage.html
    python -m http.server 8000
    # ブラウザで http://<サーバーIP>:8000/d_usage.html を開く
"""
import os
import sys
import json
import time
import argparse
from string import Template


# 非常に深いフォルダ構成でも再帰できるよう余裕を持たせる
sys.setrecursionlimit(10000)


def get_size(path):
    """指定パス以下の合計バイト数を再帰的に集計（シンボリックリンクは追わない）"""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                try:
                    total += entry.stat(follow_symlinks=False).st_size
                except (OSError, PermissionError):
                    pass
            elif entry.is_dir(follow_symlinks=False):
                total += get_size(entry.path)
    except (OSError, PermissionError):
        pass
    return total


def human_readable(size):
    """バイト数を人間が読みやすい文字列に変換"""
    if size == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(size) < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def scan_tree(path, max_depth=None, current_depth=0):
    """path 以下を走査してサイズ付きツリーを dict で返す。max_depth で表示階層を制限。"""
    try:
        entries = list(os.scandir(path))
    except (OSError, PermissionError):
        return {
            "name": os.path.basename(path) or path,
            "path": path,
            "size": 0,
            "size_h": human_readable(0),
            "children": []
        }

    children = []
    total = 0
    for entry in entries:
        if entry.is_file(follow_symlinks=False):
            try:
                fsize = entry.stat(follow_symlinks=False).st_size
            except (OSError, PermissionError):
                fsize = 0
            total += fsize
            children.append({
                "name": entry.name,
                "path": entry.path,
                "size": fsize,
                "size_h": human_readable(fsize),
                "children": []
            })
        elif entry.is_dir(follow_symlinks=False):
            if max_depth is not None and current_depth >= max_depth:
                # これ以上ツリーは展開しないが、サイズだけは再帰的に集計する
                dsize = get_size(entry.path)
                sub_children = []
            else:
                node = scan_tree(entry.path, max_depth, current_depth + 1)
                dsize = node["size"]
                sub_children = node.get("children", [])
            total += dsize
            children.append({
                "name": entry.name,
                "path": entry.path,
                "size": dsize,
                "size_h": human_readable(dsize),
                "children": sub_children
            })

    children.sort(key=lambda x: x["size"], reverse=True)
    return {
        "name": os.path.basename(path) or path,
        "path": path,
        "size": total,
        "size_h": human_readable(total),
        "children": children
    }


HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Disk Usage Visualizer - $root_label</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background: #f8f9fa; }
  h1 { font-size: 1.5em; margin-bottom: 0.3em; }
  .meta { color: #666; margin-bottom: 15px; font-size: 0.9em; }
  .container { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 20px; }
  .chart-box { flex: 1; min-width: 400px; background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); box-sizing: border-box; }
  .chart-title { font-size: 0.95em; color: #555; margin-bottom: 10px; text-align: center; }
  table { border-collapse: collapse; width: 100%; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 0.95em; }
  th, td { border-bottom: 1px solid #e0e0e0; padding: 10px 12px; text-align: left; }
  th { background: #e9ecef; }
  tr:hover { background: #f1f3f5; }
  tr.dir { cursor: pointer; }
  .breadcrumb { margin-bottom: 10px; font-size: 0.95em; }
  .breadcrumb span { cursor: pointer; color: #0d6efd; text-decoration: underline; margin-right: 4px; }
  .icon { margin-right: 6px; }
  .right { text-align: right; }
  #pieChartSvg { width: 100%; height: auto; display: block; margin: 0 auto; }
  #pieLegend { max-height: 180px; overflow-y: auto; font-size: 0.85em; margin-top: 10px; }
  #pieLegend div { margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar-row { display: flex; align-items: center; margin-bottom: 6px; font-size: 0.9em; }
  .bar-label { width: 150px; min-width: 150px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 8px; }
  .bar-track { flex: 1; background: #e9ecef; border-radius: 4px; height: 18px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; }
  .bar-value { width: 90px; min-width: 90px; text-align: right; padding-left: 8px; }
</style>
</head>
<body>
<h1>Disk Usage: $root_label</h1>
<div class="meta">合計: <span id="totalSize">$total_h</span> | 生成日時: $generated_time</div>
<div class="breadcrumb" id="breadcrumb"></div>
<div class="container">
  <div class="chart-box">
    <div class="chart-title">容量割合</div>
    <svg id="pieChartSvg" viewBox="-110 -110 220 220"></svg>
    <div id="pieLegend"></div>
  </div>
  <div class="chart-box">
    <div class="chart-title">上位項目</div>
    <div id="barChartContainer"></div>
  </div>
</div>
<table>
<thead><tr><th>名前</th><th class="right">サイズ</th><th class="right">割合</th></tr></thead>
<tbody id="tableBody"></tbody>
</table>
<script>
const treeData = $data;
let currentPath = [];
let currentData = treeData;

function humanReadable(size) {
  if (size === 0) return '0 B';
  const units = ['B','KB','MB','GB','TB','PB'];
  let i = 0;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return size.toFixed(2) + ' ' + units[i];
}

function hslColor(i, total) {
  return 'hsl(' + ((i * 137) % 360) + ', 70%, 60%)';
}

function renderPie(items, total) {
  const svg = document.getElementById('pieChartSvg');
  const legend = document.getElementById('pieLegend');
  svg.innerHTML = '';
  legend.innerHTML = '';
  if (total === 0) return;

  const radius = 90;
  let cumulative = 0;
  items.forEach(function(it, i) {
    if (it.size === 0) return;
    const startAngle = -Math.PI / 2 + (cumulative / total) * 2 * Math.PI;
    cumulative += it.size;
    const endAngle = -Math.PI / 2 + (cumulative / total) * 2 * Math.PI;
    const x1 = radius * Math.cos(startAngle);
    const y1 = radius * Math.sin(startAngle);
    const x2 = radius * Math.cos(endAngle);
    const y2 = radius * Math.sin(endAngle);
    const largeArc = (endAngle - startAngle) > Math.PI ? 1 : 0;
    const d = 'M 0 0 L ' + x1 + ' ' + y1 + ' A ' + radius + ' ' + radius + ' 0 ' + largeArc + ' 1 ' + x2 + ' ' + y2 + ' Z';
    const color = hslColor(i, items.length);

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', color);
    path.setAttribute('stroke', '#fff');
    path.setAttribute('stroke-width', '1');

    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = it.name + '\\n' + humanReadable(it.size) + ' (' + ((it.size / total) * 100).toFixed(1) + '%)';
    path.appendChild(title);
    svg.appendChild(path);

    const li = document.createElement('div');
    li.innerHTML = '<span style="display:inline-block;width:12px;height:12px;background:' + color + ';margin-right:6px;vertical-align:middle;"></span>' + it.name + ' (' + ((it.size / total) * 100).toFixed(1) + '%)';
    legend.appendChild(li);
  });
}

function renderBar(items) {
  const container = document.getElementById('barChartContainer');
  container.innerHTML = '';
  const maxSize = items.reduce(function(m, it) { return Math.max(m, it.size); }, 0);
  if (maxSize === 0) return;

  items.forEach(function(it, i) {
    const color = hslColor(i, items.length);
    const widthPct = Math.max(0.5, (it.size / maxSize) * 100);
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = '<div class="bar-label" title="' + it.name + '">' + it.name + '</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + widthPct + '%;background:' + color + ';"></div></div>' +
      '<div class="bar-value">' + humanReadable(it.size) + '</div>';
    container.appendChild(row);
  });
}

function render() {
  const items = currentData.children || [];
  const total = items.reduce(function(s, it) { return s + it.size; }, 0);

  // パンくず
  const rootSpan = '<span onclick="goUp(-1)">' + (treeData.name || treeData.path) + '</span>';
  const pathSpans = currentPath.map(function(p, i) { return '<span>/</span><span onclick="goUp(' + i + ')">' + p.name + '</span>'; }).join('');
  document.getElementById('breadcrumb').innerHTML = rootSpan + pathSpans;

  renderPie(items, total);
  renderBar(items);

  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = '';
  items.forEach(function(it) {
    const tr = document.createElement('tr');
    const isDir = it.children && it.children.length > 0;
    const icon = isDir ? '\\ud83d\\udcc1' : '\\ud83d\\udcc4';
    tr.className = isDir ? 'dir' : '';
    tr.innerHTML = '<td><span class="icon">' + icon + '</span>' + it.name + '</td>' +
                   '<td class="right">' + humanReadable(it.size) + '</td>' +
                   '<td class="right">' + (total ? ((it.size / total) * 100).toFixed(1) : 0) + '%</td>';
    if (isDir) {
      tr.addEventListener('click', function() { drillDown(it); });
    }
    tbody.appendChild(tr);
  });

  document.getElementById('totalSize').textContent = humanReadable(currentData.size);
}

function drillDown(node) {
  currentPath.push(node);
  currentData = node;
  render();
}

function goUp(level) {
  currentPath = currentPath.slice(0, level + 1);
  currentData = currentPath.reduce(function(acc, p) {
    const arr = (acc.children || acc);
    return arr.find(function(c) { return c.name === p.name; }) || acc;
  }, treeData);
  render();
}

render();
</script>
</body>
</html>""")


def generate_html(data, output_path, root_label):
    """集計結果を単体 HTML に書き出す"""
    html = HTML_TEMPLATE.substitute(
        data=json.dumps(data, ensure_ascii=False),
        root_label=root_label,
        total_h=data['size_h'],
        generated_time=time.strftime('%Y-%m-%d %H:%M:%S')
    )
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(
        description='Windows 環境向け ディスク使用容量可視化ツール (Python3.7標準モジュールのみ、オフラインOK)')
    parser.add_argument('--path', default='D:/', help='対象パス (既定: D:/ )')
    parser.add_argument('--depth', type=int, default=None,
                        help='走査する最大フォルダ階層 (未指定で無制限)')
    parser.add_argument('--output', default='disk_usage.html', help='出力HTMLファイル名')
    args = parser.parse_args()

    root = args.path
    if not os.path.exists(root):
        print(f"[ERROR] パスが存在しません: {root}")
        sys.exit(1)

    print(f"走査対象: {root}")
    print("容量を集計中... (時間がかかる場合があります)")

    tree = scan_tree(root, args.depth)

    generate_html(tree, args.output, root)
    print(f"完了: {args.output} を生成しました。")
    print(f"合計容量: {tree['size_h']}")


if __name__ == '__main__':
    main()
