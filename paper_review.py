# /// script
# requires-python = ">=3.11"
# dependencies = ["beautifulsoup4>=4.12"]
# ///
"""Build a single-file HTML review copy of a LaTeX paper.

Usage: paper-review build [config.toml] [-o out.html] [--fragment]   (default: ./paper-review.toml)
See README.md for the configuration file and the review.sty package.
"""
import argparse, base64, datetime, json, os, re, shutil, subprocess, sys, tomllib
from pathlib import Path
from bs4 import BeautifulSoup, Comment

TOOL = Path(__file__).resolve().parent
JOB = "pr-html"
DEFAULT_MACROS = {"plan": "reviewplan", "marker": "reviewmark", "todo": ["reviewtodo"]}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}


def log(msg):
    print(f"paper-review: {msg}", file=sys.stderr)


def run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


# ---------------------------------------------------------------- LaTeX side

def wrapper_tex(main, cls):
    """Wrapper that inputs the paper, swapping classes tex4ht cannot handle."""
    stub = TOOL / "tex" / "classes" / f"{cls}.tex"
    if not stub.exists():
        return f"\\input{{{main}}}\n"
    return ("% paper-review: build with article instead of " + cls + "\n"
            "\\let\\prorigdocumentclass\\documentclass\n"
            "\\renewcommand\\documentclass[2][]{\\prorigdocumentclass{article}%\n"
            "  \\let\\documentclass\\prorigdocumentclass\n"
            f"  \\input{{{stub.as_posix()}}}}}\n"
            f"\\input{{{main}}}\n")


def tex4ht_cfg(macros):
    """tex4ht configuration: review macros become marked HTML elements."""
    plan, marker = macros["plan"], macros["marker"]
    lines = [r"\Preamble{xhtml,mathml,fn-in}", r"\begin{document}", r"\ExplSyntaxOn",
             rf"\cs_if_exist:cT {{ {plan} }}",
             "  {",
             rf"    \RenewDocumentEnvironment{{{plan}}}{{+b}}",
             r"      {\ifvmode\IgnorePar\fi\EndP",
             r"       \HCode{<aside~class=``reviewplan''>}\par #1\ifvmode\IgnorePar\fi\EndP",
             r"       \HCode{</aside>}\par}{}",
             "  }",
             rf"\cs_if_exist:cT {{ {marker} }}",
             rf"  {{ \RenewDocumentCommand \{marker} {{m}}",
             r"      {\HCode{<span~class=``reviewmark''~data-item=``#1''>}[#1]\HCode{</span>}} }"]
    for todo in macros["todo"]:
        # Wrap the paper's own definition, so its formatting is kept.
        lines += [rf"\cs_if_exist:cT {{ {todo} }}",
                  rf"  {{ \cs_set_eq:cc {{ pr_orig_{todo} }} {{ {todo} }}",
                  rf"    \RenewDocumentCommand \{todo} {{m}}",
                  rf"      {{\HCode{{<span~class=``todo''>}}\use:c {{ pr_orig_{todo} }} {{#1}}\HCode{{</span>}}}} }}"]
    lines += [r"\ExplSyntaxOff", r"\EndPreamble", ""]
    # tex4ht writes HCode verbatim; `` '' stand in for the double quotes.
    return "\n".join(lines).replace("``", '"').replace("''", '"')


def build_html(paper, main, bbl, work, macros):
    if work.exists():
        shutil.rmtree(work)
    out_dir = work.parent.resolve()

    def skip(d, names):  # the repository and this tool's own output
        return [n for n in names if n in (".git", work.name) or (Path(d) / n).resolve() == out_dir]

    shutil.copytree(paper, work, ignore=skip)
    main_tex = (work / main).read_text(errors="ignore")
    m = re.search(r"^[^%\n]*\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", main_tex, re.M)
    cls = m.group(1).strip() if m else "article"
    (work / f"{JOB}.tex").write_text(wrapper_tex(Path(main).with_suffix("").as_posix(), cls))
    (work / f"{JOB}.cfg").write_text(tex4ht_cfg(macros))
    env = dict(os.environ, TEXINPUTS=f".:{TOOL / 'tex'}//:")

    if bbl:
        shutil.copy(paper / bbl, work / f"{JOB}.bbl")
    elif re.search(r"\\bibliography\{", main_tex):
        run(["pdflatex", "-interaction=nonstopmode", "-draftmode", f"{JOB}.tex"], work, env)
        r = run(["bibtex", JOB], work, env)
        if r.returncode:
            log("bibtex reported problems; see " + str(work / f"{JOB}.blg"))

    r = run(["make4ht", "-u", "-c", f"{JOB}.cfg", "-f", "html5", f"{JOB}.tex"], work, env)
    (work / "make4ht.log").write_text(r.stdout)
    errors = [l for l in (work / f"{JOB}.log").read_text(errors="ignore").splitlines() if l.startswith("!")]
    if errors:
        log(f"{len(errors)} TeX errors in the HTML build (output may be incomplete), first: {errors[0]}")
    html = work / f"{JOB}.html"
    if not html.exists():
        sys.exit(f"paper-review: make4ht produced no HTML; see {work / 'make4ht.log'}")
    log(f"class {cls}" + (" (built as article)" if (TOOL / 'tex' / 'classes' / f'{cls}.tex').exists() else ""))
    return html


# ---------------------------------------------------------------- HTML side

def image_uri(path, work):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        svg = work / "pr-variants" / (path.stem + ".svg")
        svg.parent.mkdir(exist_ok=True)
        run(["dvisvgm", "--pdf", "--no-fonts", "-o", str(svg), str(path)], work)
        if not svg.exists():
            log(f"could not convert {path} to SVG (dvisvgm --pdf needs Ghostscript)")
            return ""
        path, suffix = svg, ".svg"
    return f"data:{MIME[suffix]};base64," + base64.b64encode(path.read_bytes()).decode()


def figure_variants(cfg, cfg_dir, paper, work):
    """Variants from the config file and from \\reviewvariants in the paper."""
    figs = {}
    for label, spec in cfg.get("figures", {}).items():
        base = cfg_dir / spec.get("dir", ".")
        figs[label] = {"paper": spec.get("paper"),
                       "variants": {n: base / f for n, f in spec["variants"].items()}}
    rvar = work / f"{JOB}.rvar"
    if rvar.exists():
        for line in rvar.read_text().splitlines():
            label, paper_variant, spec = (s.strip() for s in line.split("|", 2))
            items = [kv.split("=", 1) for kv in spec.split(",") if "=" in kv]
            figs.setdefault(label, {"paper": paper_variant or None,
                                    "variants": {k.strip(): paper / v.strip() for k, v in items}})
    return figs


def assemble(html_in, work, figs, stamp_text):
    soup = BeautifulSoup(html_in.read_text(encoding="utf-8"), "html.parser")
    body = soup.body

    # Font classes: keep weight/style/variant/monospace from tex4ht's CSS, drop sizes.
    font_css = set()
    css = html_in.with_suffix(".css")
    for cls, props in re.findall(r"^\.([\w-]+)\s*\{([^}]*)\}", css.read_text() if css.exists() else "", re.M):
        keep = [p.strip() for p in props.split(";")
                if re.match(r"\s*(font-weight|font-style|font-variant)", p)
                or ("font-family" in p and "monospace" in p)]
        if keep:
            font_css.add(f".paper .{cls}{{{';'.join(keep)}}}")

    # The article class adds a date; source-line comments are noise.
    for d in body.select(".maketitle .date"):
        d.decompose()
    for c in body.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for tm in body.select(".titlemark"):
        tm.string = tm.get_text().strip().rstrip(".") + "."
    for idspan in body.select("figcaption .id"):
        idspan.string = re.sub(r"Figure\s+(\d+):?", r"Fig. \1.", idspan.get_text().strip()) + " "
    for img in body.find_all("img"):
        p = work / img.get("src", "")
        if p.is_file() and p.suffix.lower() in MIME:
            img["src"] = image_uri(p, work)
        img["alt"] = "Figure"
    for t in body.find_all("table"):
        t.wrap(soup.new_tag("div", attrs={"class": "table-scroll"}))

    # Figure label -> element id, from the aux file.
    labels = {}
    for aux in work.glob("*.aux"):
        labels.update(re.findall(r"\\newlabel\{([^}]*)\}\{\{\\rEfLiNK\{([^}]*)\}", aux.read_text(errors="ignore")))

    for label, spec in figs.items():
        fig = body.find(id=labels.get(label, "-"))
        if fig is None or fig.name != "figure":
            log(f"no figure with label {label}; variants skipped")
            continue
        cap = fig.find("figcaption")
        original = soup.new_tag("div", attrs={"class": "fig-original"})
        for node in [n for n in fig.contents if n is not cap]:
            original.append(node.extract())
        stage = soup.new_tag("div", attrs={"class": "fig-stage"})
        stage.append(original)
        bar = soup.new_tag("div", attrs={"class": "variant-bar review", "role": "group",
                                         "aria-label": f"Plot variants for {label}"})
        first = None
        for name, path in spec["variants"].items():
            if not path.is_file():
                log(f"{label}: missing variant file {path}")
                continue
            is_paper = name == spec["paper"]
            btn = soup.new_tag("button", attrs={"type": "button", "data-variant": name,
                                                "class": "variant-btn" + (" is-paper" if is_paper else "")})
            btn.string = name.replace("_", " ")
            if is_paper:
                badge = soup.new_tag("span", attrs={"class": "paper-badge"})
                badge.string = "in paper"
                btn.append(badge)
            bar.append(btn)
            stage.append(soup.new_tag("img", attrs={"class": "variant-img review", "data-variant": name,
                                                    "src": image_uri(path, work), "alt": f"{name} variant",
                                                    "hidden": ""}))
            first = first or name
        if first is None:
            continue
        fig.insert(0, bar)
        fig.insert(1, stage)
        fig.insert(2, soup.new_tag("p", attrs={"class": "variant-note review"}))
        fig["data-label"] = label
        fig["data-paper"] = spec["paper"] or ""
        fig["data-default"] = spec["paper"] or first

    # Planned structure: a Plan chip with a pop-over.
    for i, aside in enumerate(body.select("aside.reviewplan")):
        aside["id"] = f"plan-{i + 1}"
        for p in aside.find_all("p"):
            if not p.get_text(strip=True) and not p.find(True):
                p.decompose()
        aside.wrap(soup.new_tag("div", attrs={"class": "plan review"}))
        chip = soup.new_tag("button", attrs={"type": "button", "class": "plan-chip",
                                             "aria-expanded": "false", "aria-controls": aside["id"]})
        chip.string = "Plan"
        aside.insert_before(chip)
        aside["class"] = ["plan-pop"]
        aside["hidden"] = ""
        head = soup.new_tag("p", attrs={"class": "plan-head"})
        head.string = "Planned structure"
        aside.insert(0, head)
    for m in body.select(".reviewmark"):
        m["class"] = ["reviewmark", "review"]
        m["tabindex"] = "0"

    title = soup.select_one(".titleHead")
    page = (TOOL / "template.html").read_text()
    return (page.replace("{{FONT_CSS}}", "\n".join(sorted(font_css)))
                .replace("{{PAPER}}", body.decode_contents())
                .replace("{{TITLE}}", title.get_text(" ", strip=True) if title else "Paper")
                .replace("{{STAMP}}", stamp_text))


def fragment(page):
    """The page without its document skeleton (doctype, html, head, body, metas)."""
    for tag in ("<!doctype html>", '<html lang="en">', "</html>", "<head>", "</head>", "<body>", "</body>",
                '<meta charset="utf-8">', '<meta name="viewport" content="width=device-width, initial-scale=1">'):
        page = page.replace(tag + "\n", "", 1)
    return page


def stamp(paper):
    text = "Built " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    g = lambda *a: subprocess.run(["git", "-C", str(paper), *a], capture_output=True, text=True)
    head = g("rev-parse", "--abbrev-ref", "HEAD")
    if head.returncode == 0:
        text += f" from {head.stdout.strip()} @ {g('rev-parse', '--short', 'HEAD').stdout.strip()}"
        if g("status", "--porcelain", "--untracked-files=no").stdout.strip():
            text += " + uncommitted changes"
    return text


def main():
    ap = argparse.ArgumentParser(prog="paper-review", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the HTML review copy")
    b.add_argument("config", type=Path, nargs="?", default=Path("paper-review.toml"),
                   help="configuration file (default: ./paper-review.toml)")
    b.add_argument("-o", "--output", type=Path, help="output HTML (default: from the config)")
    b.add_argument("--fragment", action="store_true",
                   help="write the page without its <html>/<head>/<body> skeleton, for embedding in a host page")
    args = ap.parse_args()

    if not args.config.exists():
        sys.exit(f"paper-review: {args.config} not found")
    cfg_path = args.config.resolve()
    cfg = tomllib.loads(cfg_path.read_text())
    cfg_dir = cfg_path.parent
    paper = (cfg_dir / cfg.get("paper", ".")).resolve()
    out = (args.output.resolve() if args.output else cfg_dir / cfg.get("output", "build/paper-review/index.html"))
    work = out.parent / ".work"
    out.parent.mkdir(parents=True, exist_ok=True)
    macros = {**DEFAULT_MACROS, **cfg.get("macros", {})}

    html = build_html(paper, cfg.get("main", "main.tex"), cfg.get("bbl"), work, macros)
    figs = figure_variants(cfg, cfg_dir, paper, work)
    page = assemble(html, work, figs, stamp(paper))
    if args.fragment:
        page = fragment(page)
    out.write_text(page, encoding="utf-8")
    log(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
