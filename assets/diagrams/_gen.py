"""
مولّد رسوم بيانية SVG بسيطة ومتّسقة. كل رسمة سلسلة صناديق بأسهم،
مع تسميات فرعية اختيارية. عناوين ونصوص الصناديق بالإنجليزية فقط
(تجنبًا لمشاكل bidi rendering مع خلط الاتجاهات في نفس السطر).
"""
import html

BOX_W = 280
BOX_H = 64
GAP_Y = 32
MARGIN = 30
FONT = "Segoe UI, Arial, sans-serif"

COLORS = {
    "default": ("#EAF1FB", "#2F5496"),
    "highlight": ("#FFF3CD", "#8A6D00"),
    "danger": ("#FBEAEA", "#B23A3A"),
    "success": ("#EAF7EE", "#2E7D32"),
    "purple": ("#F1EAFB", "#6B3FA0"),
}

def esc(s):
    return html.escape(s)

def render_pipeline(title, steps, width=640):
    n = len(steps)
    height = MARGIN * 2 + 40 + n * BOX_H + (n - 1) * GAP_Y
    cx = width // 2

    svg_parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="{FONT}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>',
        f'<text x="{cx}" y="{MARGIN}" text-anchor="middle" font-size="19" '
        f'font-weight="700" fill="#1F2937">{esc(title)}</text>',
    ]

    y = MARGIN + 34
    for i, step in enumerate(steps):
        fill, stroke = COLORS.get(step.get("style", "default"), COLORS["default"])
        x = cx - BOX_W // 2
        svg_parts.append(
            f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="10" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        label = esc(step["label"])
        svg_parts.append(
            f'<text x="{cx}" y="{y + 27}" text-anchor="middle" font-size="14.5" '
            f'font-weight="600" fill="#1F2937">{label}</text>'
        )
        if step.get("sub"):
            sub = esc(step["sub"])
            svg_parts.append(
                f'<text x="{cx}" y="{y + 47}" text-anchor="middle" font-size="11.5" '
                f'fill="#4B5563">{sub}</text>'
            )
        if i < n - 1:
            arrow_y1 = y + BOX_H
            arrow_y2 = arrow_y1 + GAP_Y
            svg_parts.append(
                f'<line x1="{cx}" y1="{arrow_y1}" x2="{cx}" y2="{arrow_y2 - 8}" '
                f'stroke="#6B7280" stroke-width="2"/>'
            )
            svg_parts.append(
                f'<polygon points="{cx-6},{arrow_y2-8} {cx+6},{arrow_y2-8} {cx},{arrow_y2} " '
                f'fill="#6B7280"/>'
            )
        y += BOX_H + GAP_Y

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def render_branching(title, root, branches, width=780, box_w=220, box_h=58):
    """root: {'label','sub'} — عقدة علوية واحدة
    branches: list of lists of steps (كل قائمة عمود رأسي منفصل)"""
    n_cols = len(branches)
    col_gap = 24
    total_cols_w = n_cols * box_w + (n_cols - 1) * col_gap
    width = max(width, total_cols_w + MARGIN * 2)
    start_x = (width - total_cols_w) // 2
    max_rows = max(len(b) for b in branches)
    height = MARGIN * 2 + 40 + box_h + GAP_Y + max_rows * (box_h + 14) + (max_rows - 1) * GAP_Y + 20
    cx_root = width // 2

    svg_parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="{FONT}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>',
        f'<text x="{cx_root}" y="{MARGIN}" text-anchor="middle" font-size="19" '
        f'font-weight="700" fill="#1F2937">{esc(title)}</text>',
    ]

    root_y = MARGIN + 34
    fill, stroke = COLORS.get(root.get("style", "purple"), COLORS["purple"])
    root_x = cx_root - box_w // 2
    svg_parts.append(
        f'<rect x="{root_x}" y="{root_y}" width="{box_w}" height="{box_h}" rx="10" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
    )
    svg_parts.append(
        f'<text x="{cx_root}" y="{root_y + 25}" text-anchor="middle" font-size="14" '
        f'font-weight="700" fill="#1F2937">{esc(root["label"])}</text>'
    )
    if root.get("sub"):
        svg_parts.append(
            f'<text x="{cx_root}" y="{root_y + 43}" text-anchor="middle" font-size="10.5" '
            f'fill="#4B5563">{esc(root["sub"])}</text>'
        )

    branch_top_y = root_y + box_h + GAP_Y
    for col_i, branch in enumerate(branches):
        col_x = start_x + col_i * (box_w + col_gap)
        col_cx = col_x + box_w // 2
        # خط من الجذر لكل عمود
        svg_parts.append(
            f'<line x1="{cx_root}" y1="{root_y + box_h}" x2="{col_cx}" '
            f'y2="{branch_top_y - 6}" stroke="#9CA3AF" stroke-width="1.5"/>'
        )
        y = branch_top_y
        for i, step in enumerate(branch):
            fill, stroke = COLORS.get(step.get("style", "default"), COLORS["default"])
            svg_parts.append(
                f'<rect x="{col_x}" y="{y}" width="{box_w}" height="{box_h}" rx="9" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
            )
            svg_parts.append(
                f'<text x="{col_cx}" y="{y + 24}" text-anchor="middle" font-size="12.5" '
                f'font-weight="600" fill="#1F2937">{esc(step["label"])}</text>'
            )
            if step.get("sub"):
                svg_parts.append(
                    f'<text x="{col_cx}" y="{y + 41}" text-anchor="middle" font-size="10" '
                    f'fill="#4B5563">{esc(step["sub"])}</text>'
                )
            if i < len(branch) - 1:
                svg_parts.append(
                    f'<line x1="{col_cx}" y1="{y + box_h}" x2="{col_cx}" '
                    f'y2="{y + box_h + GAP_Y - 6}" stroke="#9CA3AF" stroke-width="1.5"/>'
                )
            y += box_h + GAP_Y

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def save(path, svg_text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg_text)
    print(f"wrote {path}")
