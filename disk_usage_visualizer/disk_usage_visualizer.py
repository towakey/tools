#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
disk_usage_visualizer.py

Windows Server 2019 / Python 3.7+ 標準モジュールのみで動作。
指定したパス（既定: D:\）以下のフォルダ・ファイル容量を再帰的に集計し、
ブラウザで可視化します。

3つのモードがあります。

1. html モード（既定）:
   単体 HTML ファイルを出力。データは HTML 内に JSON として埋め込まれます。
   ファイルサイズが大きくなる可能性があるため、小規模な対象向けです。

2. sqlite モード:
   容量データを SQLite ファイルに保存し、軽量な HTML ビューアも生成します。
   大規模な対象でも HTML が肥大化しません。

3. server モード:
   SQLite を作成（または指定）して、即座にローカル HTTP サーバーを起動します。
   ブラウザで http://<ホスト>:<ポート>/ を開くとビューアが表示されます。

使い方例:
    # 単体 HTML
    python disk_usage_visualizer.py --path D:\\ --depth 3 --output d_usage.html

    # SQLite + ビューア HTML
    python disk_usage_visualizer.py --mode sqlite --path D:\\ --depth 3 --output d_usage.db

    # サーバーを起動（走査＋閲覧）
    python disk_usage_visualizer.py --mode server --path D:\\ --depth 3 --output d_usage.db --port 8000

    # 既存の SQLite を閲覧
    python disk_usage_visualizer.py --mode server --db d_usage.db --port 8000
"""
import os
import sys
import json
import time
import html
import sqlite3
import argparse
import urllib.parse
import http.server
import shutil
import hashlib
from string import Template


# 非常に深いフォルダ構成でも再帰できるよう余裕を持たせる
sys.setrecursionlimit(10000)


def to_posix(p):
    """OS 依存のパス区切りを / に統一する"""
    p = os.path.normpath(p)
    p = p.replace(os.sep, '/')
    if os.altsep:
        p = p.replace(os.altsep, '/')
    while '//' in p:
        p = p.replace('//', '/')
    return p


def normalize_path(p):
    """入力パスを正規化。Windows のドライブルートは末尾 / を付ける"""
    p = to_posix(p)
    if len(p) == 2 and p[1] == ':':
        p += '/'
    return p


def is_root(p):
    """ルートパスか判定"""
    if p in ('', '/'):
        return True
    if len(p) == 3 and p[1] == ':' and p[2] == '/':
        return True
    return False


def parent_path(p):
    """POSIX パス p の親ディレクトリを返す"""
    if is_root(p):
        return ''
    if p.endswith('/'):
        p = p[:-1]
    idx = p.rfind('/')
    if idx == -1:
        return ''
    if idx == 0:
        return '/'
    if p[idx - 1:idx] == ':':
        return p[:idx] + '/'
    return p[:idx]


def path_name(p):
    """POSIX パス p の末尾要素名を返す"""
    if p == '':
        return ''
    if p == '/':
        return '/'
    if len(p) == 3 and p[1] == ':' and p[2] == '/':
        return p
    p = p.rstrip('/')
    return p.split('/')[-1]


def _hash_path(p):
    """パスから安全なファイル名ハッシュを生成"""
    return hashlib.sha256(p.encode('utf-8')).hexdigest()


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
    posix_path = to_posix(path)
    try:
        entries = list(os.scandir(path))
    except (OSError, PermissionError):
        return {
            "name": path_name(posix_path) or posix_path,
            "path": posix_path,
            "size": 0,
            "size_h": human_readable(0),
            "is_dir": True,
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
                "path": to_posix(entry.path),
                "size": fsize,
                "size_h": human_readable(fsize),
                "is_dir": False,
                "children": []
            })
        elif entry.is_dir(follow_symlinks=False):
            if max_depth is not None and current_depth >= max_depth:
                dsize = get_size(entry.path)
                sub_children = []
            else:
                node = scan_tree(entry.path, max_depth, current_depth + 1)
                dsize = node["size"]
                sub_children = node.get("children", [])
            total += dsize
            children.append({
                "name": entry.name,
                "path": to_posix(entry.path),
                "size": dsize,
                "size_h": human_readable(dsize),
                "is_dir": True,
                "children": sub_children
            })

    children.sort(key=lambda x: x["size"], reverse=True)
    return {
        "name": path_name(posix_path) or posix_path,
        "path": posix_path,
        "size": total,
        "size_h": human_readable(total),
        "is_dir": True,
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
  #treemapContainer { width: 100%; height: 300px; position: relative; border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden; background: #fff; }
  .tree-node { position: absolute; box-sizing: border-box; min-width: 1px; min-height: 1px; border: 1px solid #fff; overflow: hidden; display: flex; flex-direction: column; justify-content: center; align-items: flex-start; padding: 2px 4px; cursor: pointer; font-size: 0.75em; color: #222; }
  .tree-node:hover { filter: brightness(0.92); }
  .tree-node.file { cursor: default; }
  .tree-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; width: 100%; }
  .tree-value { font-size: 0.85em; opacity: 0.85; }
</style>
</head>
<body>
<h1>Disk Usage: <span id="rootLabel">$root_label</span></h1>
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
  <div class="chart-box">
    <div class="chart-title">トレーマップ（ヒートマップ）</div>
    <div id="treemapContainer"></div>
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

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(m) {
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]);
  });
}

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
    li.innerHTML = '<span style="display:inline-block;width:12px;height:12px;background:' + color + ';margin-right:6px;vertical-align:middle;"></span>' + escapeHtml(it.name) + ' (' + ((it.size / total) * 100).toFixed(1) + '%)';
    legend.appendChild(li);
  });
}

function renderBar(items, total) {
  const container = document.getElementById('barChartContainer');
  container.innerHTML = '';
  const maxSize = items.reduce(function(m, it) { return Math.max(m, it.size); }, 0);
  if (maxSize === 0) return;

  items.forEach(function(it, i) {
    const color = hslColor(i, items.length);
    const widthPct = Math.max(0.5, (it.size / maxSize) * 100);
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = '<div class="bar-label" title="' + escapeHtml(it.name) + '">' + escapeHtml(it.name) + '</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + widthPct + '%;background:' + color + ';"></div></div>' +
      '<div class="bar-value">' + humanReadable(it.size) + '</div>';
    container.appendChild(row);
  });
}

function worstAspectRatio(row, rowTotal, w, h) {
  if (rowTotal === 0 || row.length === 0) return Infinity;
  const side = Math.min(w, h);
  const area = w * h;
  const other = (rowTotal * area) / side;
  let worst = 0;
  row.forEach(function(e) {
    const len = (e.value / rowTotal) * side;
    if (len === 0) return;
    const ratio = Math.max(other / len, len / other);
    if (ratio > worst) worst = ratio;
  });
  return worst;
}

function squarify(values, x, y, w, h, result) {
  if (w <= 0 || h <= 0) return;
  if (values.length === 0) return;
  if (values.length === 1) {
    result.push({ item: values[0].item, x: x, y: y, w: w, h: h });
    return;
  }
  let row = [];
  let rowTotal = 0;
  let remaining = { x: x, y: y, w: w, h: h };
  function layoutRow() {
    if (row.length === 0) return;
    const area = remaining.w * remaining.h;
    const rowArea = rowTotal * area;
    if (remaining.w >= remaining.h) {
      const rowW = rowArea / remaining.h;
      let cy = remaining.y;
      row.forEach(function(e) {
        const h = (e.value / rowTotal) * remaining.h;
        result.push({ item: e.item, x: remaining.x, y: cy, w: rowW, h: h });
        cy += h;
      });
      remaining.x += rowW;
      remaining.w -= rowW;
    } else {
      const rowH = rowArea / remaining.w;
      let cx = remaining.x;
      row.forEach(function(e) {
        const w = (e.value / rowTotal) * remaining.w;
        result.push({ item: e.item, x: cx, y: remaining.y, w: w, h: rowH });
        cx += w;
      });
      remaining.y += rowH;
      remaining.h -= rowH;
    }
    row = [];
    rowTotal = 0;
  }
  values.forEach(function(entry) {
    if (row.length === 0) {
      row.push(entry);
      rowTotal += entry.value;
      return;
    }
    const worstWithout = worstAspectRatio(row, rowTotal, remaining.w, remaining.h);
    const newRow = row.slice();
    newRow.push(entry);
    const worstWith = worstAspectRatio(newRow, rowTotal + entry.value, remaining.w, remaining.h);
    if (worstWith <= worstWithout) {
      row.push(entry);
      rowTotal += entry.value;
    } else {
      layoutRow();
      row.push(entry);
      rowTotal += entry.value;
    }
  });
  layoutRow();
}

function renderTreemap(items, total) {
  const container = document.getElementById('treemapContainer');
  container.innerHTML = '';
  if (total === 0 || items.length === 0) return;
  const maxSize = items.reduce(function(m, it) { return Math.max(m, it.size); }, 0);
  const values = items.filter(function(it) { return it.size > 0; }).map(function(it) { return { item: it, value: it.size / total }; });
  const rects = [];
  squarify(values, 0, 0, 100, 100, rects);
  rects.forEach(function(r) {
    const it = r.item;
    const isDir = it.is_dir;
    const ratio = maxSize ? it.size / maxSize : 0;
    const hue = (1 - ratio) * 120;
    const div = document.createElement('div');
    div.className = 'tree-node' + (isDir ? '' : ' file');
    div.style.left = r.x + '%';
    div.style.top = r.y + '%';
    div.style.width = r.w + '%';
    div.style.height = r.h + '%';
    div.style.background = 'hsl(' + hue + ', 70%, 55%)';
    div.title = it.name + ' ' + humanReadable(it.size) + ' (' + ((it.size / total) * 100).toFixed(1) + '%)';
    const label = document.createElement('div');
    label.className = 'tree-label';
    label.textContent = it.name;
    const value = document.createElement('div');
    value.className = 'tree-value';
    value.textContent = humanReadable(it.size);
    if (r.w >= 12 && r.h >= 8) {
      div.appendChild(label);
      if (r.h >= 14) {
        div.appendChild(value);
      }
    }
    if (isDir) {
      div.addEventListener('click', function() { drillDown(it); });
    }
    container.appendChild(div);
  });
}

function render() {
  const items = currentData.children || [];
  const total = items.reduce(function(s, it) { return s + it.size; }, 0);

  const rootSpan = '<span onclick="goUp(-1)">' + escapeHtml(treeData.name || treeData.path) + '</span>';
  const pathSpans = currentPath.map(function(p, i) { return '<span>/</span><span onclick="goUp(' + i + ')">' + escapeHtml(p.name) + '</span>'; }).join('');
  document.getElementById('breadcrumb').innerHTML = rootSpan + pathSpans;

  renderPie(items, total);
  renderBar(items, total);
  renderTreemap(items, total);

  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = '';
  items.forEach(function(it) {
    const tr = document.createElement('tr');
    const isDir = it.is_dir;
    const icon = isDir ? '\\ud83d\\udcc1' : '\\ud83d\\udcc4';
    tr.className = isDir ? 'dir' : '';
    tr.innerHTML = '<td><span class="icon">' + icon + '</span>' + escapeHtml(it.name) + '</td>' +
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
  if (level === -1) {
    currentPath = [];
    currentData = treeData;
  } else {
    currentPath = currentPath.slice(0, level + 1);
    currentData = currentPath[level];
  }
  render();
}

render();
</script>
</body>
</html>""")


VIEWER_TEMPLATE = Template("""<!DOCTYPE html>
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
  #treemapContainer { width: 100%; height: 300px; position: relative; border: 1px solid #e0e0e0; border-radius: 4px; overflow: hidden; background: #fff; }
  .tree-node { position: absolute; box-sizing: border-box; min-width: 1px; min-height: 1px; border: 1px solid #fff; overflow: hidden; display: flex; flex-direction: column; justify-content: center; align-items: flex-start; padding: 2px 4px; cursor: pointer; font-size: 0.75em; color: #222; }
  .tree-node:hover { filter: brightness(0.92); }
  .tree-node.file { cursor: default; }
  .tree-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; width: 100%; }
  .tree-value { font-size: 0.85em; opacity: 0.85; }
</style>
</head>
<body data-root="$root_path" data-root-name="$root_label">
<h1>Disk Usage: <span id="rootLabel"></span></h1>
<div class="meta">合計: <span id="totalSize">-</span> | 生成日時: $generated_time</div>
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
  <div class="chart-box">
    <div class="chart-title">トレーマップ（ヒートマップ）</div>
    <div id="treemapContainer"></div>
  </div>
</div>
<table>
<thead><tr><th>名前</th><th class="right">サイズ</th><th class="right">割合</th></tr></thead>
<tbody id="tableBody"></tbody>
</table>
<script>
const ROOT_PATH = document.body.getAttribute('data-root');
const ROOT_NAME = document.body.getAttribute('data-root-name');
let treeData = { name: ROOT_NAME, path: ROOT_PATH, size: 0, is_dir: true, children: [] };
let currentPath = [];
let currentData = treeData;

document.getElementById('rootLabel').textContent = ROOT_NAME;

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(m) {
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]);
  });
}

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
    li.innerHTML = '<span style="display:inline-block;width:12px;height:12px;background:' + color + ';margin-right:6px;vertical-align:middle;"></span>' + escapeHtml(it.name) + ' (' + ((it.size / total) * 100).toFixed(1) + '%)';
    legend.appendChild(li);
  });
}

function renderBar(items, total) {
  const container = document.getElementById('barChartContainer');
  container.innerHTML = '';
  const maxSize = items.reduce(function(m, it) { return Math.max(m, it.size); }, 0);
  if (maxSize === 0) return;

  items.forEach(function(it, i) {
    const color = hslColor(i, items.length);
    const widthPct = Math.max(0.5, (it.size / maxSize) * 100);
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = '<div class="bar-label" title="' + escapeHtml(it.name) + '">' + escapeHtml(it.name) + '</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + widthPct + '%;background:' + color + ';"></div></div>' +
      '<div class="bar-value">' + humanReadable(it.size) + '</div>';
    container.appendChild(row);
  });
}

function worstAspectRatio(row, rowTotal, w, h) {
  if (rowTotal === 0 || row.length === 0) return Infinity;
  const side = Math.min(w, h);
  const area = w * h;
  const other = (rowTotal * area) / side;
  let worst = 0;
  row.forEach(function(e) {
    const len = (e.value / rowTotal) * side;
    if (len === 0) return;
    const ratio = Math.max(other / len, len / other);
    if (ratio > worst) worst = ratio;
  });
  return worst;
}

function squarify(values, x, y, w, h, result) {
  if (w <= 0 || h <= 0) return;
  if (values.length === 0) return;
  if (values.length === 1) {
    result.push({ item: values[0].item, x: x, y: y, w: w, h: h });
    return;
  }
  let row = [];
  let rowTotal = 0;
  let remaining = { x: x, y: y, w: w, h: h };
  function layoutRow() {
    if (row.length === 0) return;
    const area = remaining.w * remaining.h;
    const rowArea = rowTotal * area;
    if (remaining.w >= remaining.h) {
      const rowW = rowArea / remaining.h;
      let cy = remaining.y;
      row.forEach(function(e) {
        const h = (e.value / rowTotal) * remaining.h;
        result.push({ item: e.item, x: remaining.x, y: cy, w: rowW, h: h });
        cy += h;
      });
      remaining.x += rowW;
      remaining.w -= rowW;
    } else {
      const rowH = rowArea / remaining.w;
      let cx = remaining.x;
      row.forEach(function(e) {
        const w = (e.value / rowTotal) * remaining.w;
        result.push({ item: e.item, x: cx, y: remaining.y, w: w, h: rowH });
        cx += w;
      });
      remaining.y += rowH;
      remaining.h -= rowH;
    }
    row = [];
    rowTotal = 0;
  }
  values.forEach(function(entry) {
    if (row.length === 0) {
      row.push(entry);
      rowTotal += entry.value;
      return;
    }
    const worstWithout = worstAspectRatio(row, rowTotal, remaining.w, remaining.h);
    const newRow = row.slice();
    newRow.push(entry);
    const worstWith = worstAspectRatio(newRow, rowTotal + entry.value, remaining.w, remaining.h);
    if (worstWith <= worstWithout) {
      row.push(entry);
      rowTotal += entry.value;
    } else {
      layoutRow();
      row.push(entry);
      rowTotal += entry.value;
    }
  });
  layoutRow();
}

function renderTreemap(items, total) {
  const container = document.getElementById('treemapContainer');
  container.innerHTML = '';
  if (total === 0 || items.length === 0) return;
  const maxSize = items.reduce(function(m, it) { return Math.max(m, it.size); }, 0);
  const values = items.filter(function(it) { return it.size > 0; }).map(function(it) { return { item: it, value: it.size / total }; });
  const rects = [];
  squarify(values, 0, 0, 100, 100, rects);
  rects.forEach(function(r) {
    const it = r.item;
    const isDir = it.is_dir;
    const ratio = maxSize ? it.size / maxSize : 0;
    const hue = (1 - ratio) * 120;
    const div = document.createElement('div');
    div.className = 'tree-node' + (isDir ? '' : ' file');
    div.style.left = r.x + '%';
    div.style.top = r.y + '%';
    div.style.width = r.w + '%';
    div.style.height = r.h + '%';
    div.style.background = 'hsl(' + hue + ', 70%, 55%)';
    div.title = it.name + ' ' + humanReadable(it.size) + ' (' + ((it.size / total) * 100).toFixed(1) + '%)';
    const label = document.createElement('div');
    label.className = 'tree-label';
    label.textContent = it.name;
    const value = document.createElement('div');
    value.className = 'tree-value';
    value.textContent = humanReadable(it.size);
    if (r.w >= 12 && r.h >= 8) {
      div.appendChild(label);
      if (r.h >= 14) {
        div.appendChild(value);
      }
    }
    if (isDir) {
      div.addEventListener('click', function() { drillDown(it); });
    }
    container.appendChild(div);
  });
}

function render() {
  const items = currentData.children || [];
  const total = items.reduce(function(s, it) { return s + it.size; }, 0);

  const rootSpan = '<span onclick="goUp(-1)">' + escapeHtml(treeData.name || treeData.path) + '</span>';
  const pathSpans = currentPath.map(function(p, i) { return '<span>/</span><span onclick="goUp(' + i + ')">' + escapeHtml(p.name) + '</span>'; }).join('');
  document.getElementById('breadcrumb').innerHTML = rootSpan + pathSpans;

  renderPie(items, total);
  renderBar(items, total);
  renderTreemap(items, total);

  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = '';
  items.forEach(function(it) {
    const tr = document.createElement('tr');
    const isDir = it.is_dir;
    const icon = isDir ? '\\ud83d\\udcc1' : '\\ud83d\\udcc4';
    tr.className = isDir ? 'dir' : '';
    tr.innerHTML = '<td><span class="icon">' + icon + '</span>' + escapeHtml(it.name) + '</td>' +
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
  if (node.is_dir && !node.children) {
    fetch('/api/children?path=' + encodeURIComponent(node.path))
      .then(function(r) { return r.json(); })
      .then(function(data) {
        node.children = data;
        currentPath.push(node);
        currentData = node;
        render();
      })
      .catch(function(e) { console.error('load error', e); });
    return;
  }
  currentPath.push(node);
  currentData = node;
  render();
}

function goUp(level) {
  if (level === -1) {
    currentPath = [];
    currentData = treeData;
  } else {
    currentPath = currentPath.slice(0, level + 1);
    currentData = currentPath[level];
  }
  render();
}

function loadInfo(p) {
  return fetch('/api/info?path=' + encodeURIComponent(p)).then(function(r) { return r.json(); });
}

function loadRoot() {
  loadInfo(ROOT_PATH).then(function(info) {
    treeData.size = info.size;
    return fetch('/api/children?path=' + encodeURIComponent(ROOT_PATH)).then(function(r) { return r.json(); });
  }).then(function(children) {
    treeData.children = children;
    currentData = treeData;
    render();
  }).catch(function(e) { console.error('init error', e); });
}

loadRoot();
</script>
</body>
</html>""")


_SPLIT_JS = """<script src="paths.js"></script>
<script>window.__duData = {};</script>
<script>
function __splitMakeResponse(obj) { return { json: function() { return Promise.resolve(obj); } }; }
function __splitFetch(url, options) {
  return new Promise(function(resolve, reject) {
    var m = url.match(/^\\/?api\\/(children|info)\\?path=(.+)$$/);
    if (!m) { reject(new Error('unknown url: ' + url)); return; }
    var action = m[1];
    var path = decodeURIComponent(m[2]);
    var h = window.__duPaths[path];
    if (!h) {
      if (action === 'children') { resolve(__splitMakeResponse([])); return; }
      reject(new Error('not found: ' + path)); return;
    }
    if (window.__duData[h]) {
      resolve(__splitMakeResponse(action === 'info' ? window.__duData[h] : window.__duData[h].children));
      return;
    }
    var s = document.createElement('script');
    s.src = 'data/' + h.substring(0, 2) + '/' + h + '.js';
    s.onload = function() {
      resolve(__splitMakeResponse(action === 'info' ? window.__duData[h] : window.__duData[h].children));
    };
    s.onerror = function() { reject(new Error('load error: ' + path)); };
    document.head.appendChild(s);
  });
}
window.fetch = __splitFetch;
function __splitParentPath(p) {
  if (p === ROOT_PATH) return '';
  if (p.length === 3 && p[1] === ':' && p[2] === '/') return '';
  if (p === '/') return '';
  if (p.endsWith('/')) p = p.slice(0, -1);
  var idx = p.lastIndexOf('/');
  if (idx === -1) return '';
  if (idx === 0) return '/';
  if (p[idx - 1] === ':') return p.slice(0, idx) + '/';
  return p.slice(0, idx);
}
function navigateToStart() {
  var params = new URLSearchParams(window.location.search);
  var start = params.get('path') || ROOT_PATH;
  if (start === ROOT_PATH) { loadRoot(); return; }
  var chain = [];
  var p = start;
  var guard = 0;
  while (p && p !== ROOT_PATH && guard < 100) {
    chain.unshift(p);
    p = __splitParentPath(p);
    guard++;
  }
  loadInfo(ROOT_PATH).then(function(root) {
    treeData = root;
    currentData = root;
    currentPath = [];
    var i = 0;
    function next() {
      if (i >= chain.length) { render(); return; }
      var target = chain[i];
      var child = currentData.children.find(function(c) { return c.path === target; });
      if (!child) { console.warn('target not found', target); render(); return; }
      loadInfo(child.path).then(function(data) {
        currentPath.push(data);
        currentData = data;
        i++;
        next();
      }).catch(function(e) { console.error(e); render(); });
    }
    next();
  }).catch(function(e) { console.error(e); });
}
</script>
"""
SPLIT_TEMPLATE = Template(VIEWER_TEMPLATE.template.replace('</head>', _SPLIT_JS + '</head>').replace('loadRoot();\n</script>', 'navigateToStart();\n</script>'))


def _ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS entries (
        path TEXT PRIMARY KEY,
        parent TEXT,
        name TEXT,
        size INTEGER,
        is_dir INTEGER,
        depth INTEGER
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_parent ON entries(parent)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_path ON entries(path)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_depth ON entries(depth)')


def _insert_entry(conn, path, parent, name, size, is_dir, depth):
    conn.execute(
        'INSERT OR REPLACE INTO entries (path, parent, name, size, is_dir, depth) VALUES (?, ?, ?, ?, ?, ?)',
        (path, parent, name, size, 1 if is_dir else 0, depth)
    )


def _scan_dir_sqlite(path, conn, max_depth=None, current_depth=0):
    """path 以下を走査して SQLite に格納。ディレクトリの合計サイズを返す。"""
    try:
        entries = list(os.scandir(path))
    except (OSError, PermissionError):
        return 0

    total = 0
    current_p = to_posix(path)

    for entry in entries:
        if entry.is_file(follow_symlinks=False):
            try:
                fsize = entry.stat(follow_symlinks=False).st_size
            except (OSError, PermissionError):
                fsize = 0
            total += fsize
            entry_p = to_posix(entry.path)
            _insert_entry(conn, entry_p, current_p, entry.name, fsize, False, current_depth + 1)
        elif entry.is_dir(follow_symlinks=False):
            if max_depth is not None and current_depth >= max_depth:
                dsize = get_size(entry.path)
            else:
                dsize = _scan_dir_sqlite(entry.path, conn, max_depth, current_depth + 1)
            total += dsize
            entry_p = to_posix(entry.path)
            _insert_entry(conn, entry_p, current_p, entry.name, dsize, True, current_depth + 1)

    name = path_name(current_p)
    parent_p = parent_path(current_p)
    _insert_entry(conn, current_p, parent_p, name, total, True, current_depth)
    return total


def scan_to_sqlite(path, db_path, max_depth=None):
    """対象パスを走査し、SQLite ファイルに格納する"""
    conn = sqlite3.connect(db_path)
    conn.isolation_level = None
    try:
        conn.execute('BEGIN')
        _ensure_schema(conn)
        _scan_dir_sqlite(path, conn, max_depth, 0)
        conn.commit()
    finally:
        conn.close()


def _write_split_page(path, data, out_dir):
    """分割用データファイル (data/*.js) を書き出す"""
    h = _hash_path(path)
    prefix = h[:2]
    data_dir = os.path.join(out_dir, 'data', prefix)
    os.makedirs(data_dir, exist_ok=True)
    page_path = os.path.join(data_dir, h + '.js')
    with open(page_path, 'w', encoding='utf-8') as f:
        f.write(f"window.__duData['{h}'] = " + json.dumps(data, ensure_ascii=False) + ';')


def _generate_split(path, out_dir, mapping, max_depth=None, current_depth=0):
    """path 以下を走査し、各ディレクトリごとに .js ファイルを出力する"""
    try:
        entries = list(os.scandir(path))
    except (OSError, PermissionError):
        entries = []

    children = []
    total = 0
    current_p = to_posix(path)

    for entry in entries:
        if entry.is_file(follow_symlinks=False):
            try:
                fsize = entry.stat(follow_symlinks=False).st_size
            except (OSError, PermissionError):
                fsize = 0
            total += fsize
            children.append({
                'name': entry.name,
                'path': to_posix(entry.path),
                'size': fsize,
                'size_h': human_readable(fsize),
                'is_dir': False,
                'has_page': False
            })
        elif entry.is_dir(follow_symlinks=False):
            child_p = to_posix(entry.path)
            child_has_page = (max_depth is None or current_depth < max_depth)
            if child_has_page:
                dsize = _generate_split(entry.path, out_dir, mapping, max_depth, current_depth + 1)
            else:
                dsize = get_size(entry.path)
            total += dsize
            children.append({
                'name': entry.name,
                'path': child_p,
                'size': dsize,
                'size_h': human_readable(dsize),
                'is_dir': True,
                'has_page': child_has_page
            })

    children.sort(key=lambda x: x['size'], reverse=True)
    page_data = {
        'name': path_name(current_p),
        'path': current_p,
        'parent': parent_path(current_p),
        'size': total,
        'size_h': human_readable(total),
        'is_dir': True,
        'has_page': True,
        'children': children
    }
    _write_split_page(current_p, page_data, out_dir)
    mapping[current_p] = _hash_path(current_p)
    return total


def generate_split_site(path, out_dir, max_depth=None):
    """サーバー不要で閲覧できる静的サイトを生成する"""
    root = normalize_path(path)
    if not os.path.exists(root):
        raise FileNotFoundError(f'パスが存在しません: {root}')

    os.makedirs(out_dir, exist_ok=True)
    data_root = os.path.join(out_dir, 'data')
    if os.path.exists(data_root):
        shutil.rmtree(data_root)

    mapping = {}
    _generate_split(root, out_dir, mapping, max_depth, 0)

    with open(os.path.join(out_dir, 'paths.js'), 'w', encoding='utf-8') as f:
        f.write('window.__duPaths = ' + json.dumps(mapping, ensure_ascii=False) + ';')

    root_label = path_name(root)
    page_html = SPLIT_TEMPLATE.substitute(
        root_path=html.escape(root),
        root_label=html.escape(root_label),
        generated_time=time.strftime('%Y-%m-%d %H:%M:%S')
    )
    with open(os.path.join(out_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(page_html)

    return out_dir


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


def generate_viewer_html(root_path, root_label):
    """サーバー／SQLite 連携用の軽量 HTML ビューア文字列を返す"""
    return VIEWER_TEMPLATE.substitute(
        root_path=html.escape(root_path),
        root_label=html.escape(root_label),
        generated_time=time.strftime('%Y-%m-%d %H:%M:%S')
    )


def generate_viewer_html_file(db_path, root_path, root_label=None):
    """SQLite ファイルの隣にビューア HTML を書き出す"""
    if root_label is None:
        root_label = path_name(root_path)
    viewer_path = os.path.splitext(db_path)[0] + '_viewer.html'
    html = generate_viewer_html(root_path, root_label)
    with open(viewer_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return viewer_path


class DiskUsageHandler(http.server.BaseHTTPRequestHandler):
    db_path = None
    root_path = None
    root_name = None
    viewer_html = None

    def log_message(self, fmt, *args):
        # 必要に応じて print(self.log_date_time_string(), fmt % args)
        pass

    def _send(self, code, content_type, body):
        self.send_response(code)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self._send(code, 'application/json', body)

    def _send_html(self, html_str, code=200):
        body = html_str.encode('utf-8')
        self._send(code, 'text/html', body)

    def _query(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ('/', '/index.html', '/viewer.html'):
            self._send_html(self.viewer_html)
            return

        params = urllib.parse.parse_qs(parsed.query)

        if path == '/api/children':
            p = params.get('path', [''])[0]
            data = self._query(
                'SELECT name, path, size, is_dir FROM entries WHERE parent = ? ORDER BY size DESC',
                (p,)
            )
            self._send_json(data)
            return

        if path == '/api/info':
            p = params.get('path', [''])[0]
            rows = self._query(
                'SELECT name, path, size, is_dir FROM entries WHERE path = ? LIMIT 1',
                (p,)
            )
            if rows:
                self._send_json(rows[0])
            else:
                self.send_error(404)
            return

        if path == '/api/search':
            q = params.get('query', [''])[0]
            if not q:
                self._send_json([])
                return
            like = '%' + q + '%'
            data = self._query(
                'SELECT name, path, size, is_dir FROM entries WHERE name LIKE ? OR path LIKE ? ORDER BY size DESC LIMIT 100',
                (like, like)
            )
            self._send_json(data)
            return

        self.send_error(404)


def run_server(db_path, host, port, root_path=None, root_name=None):
    """SQLite データを配信する HTTP サーバーを起動する"""
    if root_path is None:
        conn = sqlite3.connect(db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT path, name FROM entries WHERE depth = 0 AND is_dir = 1 LIMIT 1").fetchone()
            if not row:
                print('[ERROR] DB にルートディレクトリが見つかりません')
                sys.exit(1)
            root_path = row['path']
            root_name = row['name']
        finally:
            conn.close()

    if root_name is None:
        root_name = path_name(root_path)

    viewer_html = generate_viewer_html(root_path, root_name)

    DiskUsageHandler.db_path = db_path
    DiskUsageHandler.root_path = root_path
    DiskUsageHandler.root_name = root_name
    DiskUsageHandler.viewer_html = viewer_html

    server = http.server.HTTPServer((host, port), DiskUsageHandler)
    print(f'サーバーを起動しました: http://{host}:{port}')
    print(f'ルート: {root_path}')
    print('Ctrl+C で停止します')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(
        description='Windows 環境向け ディスク使用容量可視化ツール (Python3.7標準モジュールのみ、オフラインOK)'
    )
    parser.add_argument('--mode', choices=['html', 'sqlite', 'server', 'split'], default='html',
                        help='出力モード: html=単体HTML, sqlite=SQLite+ビューア, server=SQLite+HTTPサーバー, split=静的HTML分割 (既定: html)')
    parser.add_argument('--path', default='D:/', help='対象パス (既定: D:/ )')
    parser.add_argument('--depth', type=int, default=None,
                        help='走査する最大フォルダ階層 (未指定で無制限)')
    parser.add_argument('--output', help='出力ファイル (html/sqlite) または出力ディレクトリ (split)')
    parser.add_argument('--db', help='server モードで使用する既存の SQLite ファイル')
    parser.add_argument('--host', default='127.0.0.1', help='server ホスト (既定: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8000, help='server ポート (既定: 8000)')
    args = parser.parse_args()

    if args.mode == 'html':
        if not args.output:
            args.output = 'disk_usage.html'
        root = normalize_path(args.path)
        if not os.path.exists(root):
            print(f'[ERROR] パスが存在しません: {root}')
            sys.exit(1)
        print(f'走査対象: {root}')
        print('容量を集計中... (時間がかかる場合があります)')
        tree = scan_tree(root, args.depth)
        generate_html(tree, args.output, root)
        print(f'完了: {args.output} を生成しました。')
        print(f'合計容量: {tree["size_h"]}')

    elif args.mode == 'sqlite':
        if not args.output:
            args.output = 'disk_usage.db'
        root = normalize_path(args.path)
        if not os.path.exists(root):
            print(f'[ERROR] パスが存在しません: {root}')
            sys.exit(1)
        print(f'走査対象: {root}')
        print('容量を集計中... (時間がかかる場合があります)')
        scan_to_sqlite(root, args.output, args.depth)
        viewer = generate_viewer_html_file(args.output, root)
        print(f'完了: {args.output} を生成しました。')
        print(f'ビューア: {viewer}')
        print('以下のコマンドでサーバーを起動できます:')
        print(f'  python disk_usage_visualizer.py --mode server --db {args.output} --port {args.port}')

    elif args.mode == 'split':
        if not args.output:
            args.output = 'disk_usage_site'
        root = normalize_path(args.path)
        if not os.path.exists(root):
            print(f'[ERROR] パスが存在しません: {root}')
            sys.exit(1)
        print(f'走査対象: {root}')
        print('容量を集計中... (時間がかかる場合があります)')
        out_dir = generate_split_site(root, args.output, args.depth)
        print(f'完了: {out_dir}/index.html を生成しました。')
        print('index.html をブラウザで開いてください (Pythonサーバー不要)。')

    elif args.mode == 'server':
        if args.db:
            db_path = args.db
            root = None
        else:
            if not args.output:
                args.output = 'disk_usage.db'
            db_path = args.output
            root = normalize_path(args.path)
            if not os.path.exists(root):
                print(f'[ERROR] パスが存在しません: {root}')
                sys.exit(1)
            print(f'走査対象: {root}')
            print('容量を集計中... (時間がかかる場合があります)')
            scan_to_sqlite(root, db_path, args.depth)
            viewer = generate_viewer_html_file(db_path, root)
            print(f'ビューアも生成しました: {viewer}')

        if not os.path.exists(db_path):
            print(f'[ERROR] DB が存在しません: {db_path}')
            sys.exit(1)

        run_server(db_path, args.host, args.port, root)


if __name__ == '__main__':
    main()
