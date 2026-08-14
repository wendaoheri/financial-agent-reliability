#!/usr/bin/env python3
"""Deterministic renderer: stage5_full_report.md -> stage5_full_report.html.

Supports the markdown subset used by the Stage 5 full report: headings,
tables, lists, blockquotes, fenced code blocks, inline code/bold/links.
Produces accessible, self-contained zh-CN HTML (skip link, scoped headers,
no color-only meaning).
"""

from __future__ import annotations

import html
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE = ROOT / "stage5_full_report.md"
TARGET = ROOT / "stage5_full_report.html"


def inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def render(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    table_buffer: list[str] = []
    list_stack: list[str] = []
    quote_buffer: list[str] = []
    code_buffer: list[str] | None = None
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def flush_table() -> None:
        if not table_buffer:
            return
        rows = [r for r in table_buffer if not re.fullmatch(r"\|[\s:\-|]+\|", r)]
        parsed = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
        out.append('<div class="table-wrap"><table>')
        if parsed:
            out.append("<thead><tr>"
                       + "".join(f'<th scope="col">{inline(c)}</th>' for c in parsed[0])
                       + "</tr></thead>")
        out.append("<tbody>")
        for row in parsed[1:]:
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
        out.append("</tbody></table></div>")
        table_buffer.clear()

    def flush_list() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    def flush_quote() -> None:
        if quote_buffer:
            inner = []
            for q in quote_buffer:
                if q.startswith("## "):
                    inner.append(f"<h2>{inline(q[3:])}</h2>")
                elif q.strip():
                    inner.append(f"<p>{inline(q)}</p>")
            out.append('<blockquote role="note" class="alert">' + "".join(inner) + "</blockquote>")
            quote_buffer.clear()

    for raw in lines:
        line = raw.rstrip()
        if code_buffer is not None:
            if line.strip().startswith("```"):
                out.append("<pre><code>" + html.escape("\n".join(code_buffer)) + "</code></pre>")
                code_buffer = None
            else:
                code_buffer.append(raw)
            continue
        if line.strip().startswith("```"):
            flush_paragraph(); flush_table(); flush_list(); flush_quote()
            code_buffer = []
            continue
        if line.startswith("|"):
            flush_paragraph(); flush_list(); flush_quote()
            table_buffer.append(line)
            continue
        flush_table()
        if line.startswith(">"):
            flush_paragraph(); flush_list()
            quote_buffer.append(line.lstrip("> "))
            continue
        flush_quote()
        if not line.strip():
            flush_paragraph(); flush_list()
            continue
        if line.startswith("---"):
            flush_paragraph(); flush_list()
            out.append("<hr>")
            continue
        heading = re.match(r"(#{1,6})\s+(.*)", line)
        if heading:
            flush_paragraph(); flush_list()
            level = len(heading.group(1))
            text = heading.group(2)
            slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text).strip("-").lower()
            out.append(f'<h{level} id="{slug}">{inline(text)}</h{level}>')
            continue
        ordered = re.match(r"\s*(\d+)\.\s+(.*)", line)
        if ordered:
            flush_paragraph()
            if not list_stack or list_stack[-1] != "ol":
                flush_list()
                out.append("<ol>")
                list_stack.append("ol")
            out.append(f"<li>{inline(ordered.group(2))}</li>")
            continue
        if re.match(r"\s*-\s+", line):
            flush_paragraph()
            if not list_stack or list_stack[-1] != "ul":
                flush_list()
                out.append("<ul>")
                list_stack.append("ul")
            item = re.sub(r"^\s*-\s+", "", line)
            out.append(f"<li>{inline(item)}</li>")
            continue
        flush_list()
        paragraph.append(line.strip())
    if code_buffer is not None:
        out.append("<pre><code>" + html.escape("\n".join(code_buffer)) + "</code></pre>")
    flush_paragraph(); flush_table(); flush_list(); flush_quote()

    body = "\n".join(out)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Financial Agentic Index v0.1 —— Stage 5 排行榜、报告与客户演示（保留主排名模式）</title>
<style>
body{{font:16px/1.65 system-ui,"PingFang SC","Microsoft YaHei",sans-serif;max-width:1080px;margin:auto;padding:1.5rem;color:#1a1a1a}}
.skip{{position:absolute;left:-9999px}}
.skip:focus{{left:1rem;top:1rem;background:#fff;padding:.5rem;z-index:10}}
h1{{font-size:1.7rem;line-height:1.3}}h2{{font-size:1.3rem;margin-top:2rem;border-bottom:2px solid #ccc;padding-bottom:.3rem}}h3{{font-size:1.1rem}}
blockquote.alert{{border:3px solid #b45309;border-left-width:8px;background:#fffbeb;padding:1rem 1.25rem;margin:1.25rem 0}}
blockquote.alert h2{{border:none;margin:0 0 .5rem;font-size:1.15rem}}
.table-wrap{{overflow-x:auto;margin:1rem 0}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #888;padding:.45rem .6rem;vertical-align:top;text-align:left}}
th{{background:#f3f4f6}}
code{{background:#f3f4f6;padding:.1rem .3rem;overflow-wrap:anywhere;font-size:.9em}}
pre{{background:#f8f8f8;border:1px solid #ddd;padding:1rem;overflow-x:auto}}
pre code{{background:none;padding:0}}
hr{{border:none;border-top:1px solid #ccc;margin:2rem 0}}
a{{color:#1d4ed8}}
</style>
</head>
<body>
<a class="skip" href="#main">跳到主要内容</a>
<main id="main">
{body}
</main>
</body>
</html>
"""


def main() -> int:
    TARGET.write_text(render(SOURCE.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"rendered {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
