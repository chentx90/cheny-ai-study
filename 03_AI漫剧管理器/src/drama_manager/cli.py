"""
AI漫剧管理器 CLI

drama init <name>           创建项目
drama list                  列出项目
drama info                  项目信息
drama novel import <file>   导入小说
drama novel convert         AI转换分镜
drama novel split           交互式分集
drama panel list|show|edit  分镜管理
drama entity list|show|add|extract  实体管理
drama prompt infer          提示词推理
drama variable list|set|get 变量管理
drama agent run             一键全流程
drama git log|diff|revert   版本管理
"""
import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel as RichPanel

from drama_manager import store
from drama_manager.version.vcs import ProjectVCS

app = typer.Typer(help="AI漫剧管理器 - 小说转剧本CLI工具")
console = Console()
_active_project: str | None = None


def _require_project() -> dict:
    """
    获取当前操作的项目。

    优先级:
    1. 进程内缓存 _active_project (同一进程内多次调用复用)
    2. 持久化的活动项目 data/.active (drama use 设置)
    3. 最近创建的项目 (兜底，并自动设为活动项目)

    没有任何项目时报错退出。
    """
    global _active_project
    # 1. 进程内缓存
    if _active_project:
        p = store.get_project(_active_project)
        if p:
            return p
    # 2. 持久化的活动项目
    pid = store.get_active_project_id()
    if pid:
        p = store.get_project(pid)
        if p:
            _active_project = pid
            return p
    # 3. 兜底: 最近创建的项目
    projects = store.list_projects()
    if not projects:
        console.print("[red]没有项目，请先: drama init <name>[/red]")
        raise typer.Exit(1)
    _active_project = projects[0]["id"]
    store.set_active_project_id(_active_project)
    return projects[0]


def _get_vcs(pid: str) -> ProjectVCS:
    from drama_manager.config import get_projects_dir
    return ProjectVCS(get_projects_dir() / pid)


def _commit_and_log(pid: str, command: str, detail: str):
    """
    统一处理「写操作日志 + git commit」。

    所有数据写命令调用此函数，保证 operations.jsonl 和 git 历史同步记录。
    git commit 信息复用 "command: detail" 格式。

    Args:
        pid:     项目 id
        command: 操作命令名 (如 "convert" / "extract")
        detail:  详情 (如 "107分镜")
    """
    store.log_operation(pid, command, detail)
    _get_vcs(pid).commit(f"{command}: {detail}")


# ── 项目管理 ──

@app.command()
def init(name: str):
    """创建新项目"""
    p = store.create_project(name)
    _get_vcs(p["id"]).init()
    # 新建项目自动设为当前活动项目
    store.set_active_project_id(p["id"])
    console.print(RichPanel(f"[bold]{name}[/bold] ({p['id']})", title="OK", border_style="green"))


@app.command()
def use(project_id: str):
    """切换当前活动项目"""
    p = store.get_project(project_id)
    if not p:
        # 支持用名称前缀模糊匹配
        matches = [x for x in store.list_projects() if x["id"].startswith(project_id) or x["name"] == project_id]
        if len(matches) == 1:
            p = matches[0]
        elif len(matches) > 1:
            console.print(f"[yellow]'{project_id}' 匹配到多个项目，请用完整 ID[/yellow]")
            for m in matches:
                console.print(f"  {m['id']}  {m['name']}")
            raise typer.Exit(1)
        else:
            console.print(f"[red]项目不存在: {project_id}[/red]"); raise typer.Exit(1)
    store.set_active_project_id(p["id"])
    console.print(f"[green]当前项目: {p['name']} ({p['id']})[/green]")


@app.command("log")
def show_log(n: int = typer.Option(30, help="显示最近 N 条")):
    """查看当前项目的操作日志"""
    project = _require_project()
    records = store.load_operations(project["id"], limit=n)
    if not records:
        console.print("[yellow]暂无操作日志[/yellow]"); return
    t = Table(title=f"操作日志 - {project['name']}")
    t.add_column("时间", style="cyan", width=20)
    t.add_column("操作", style="bold", width=14)
    t.add_column("详情")
    for r in records:
        t.add_row(r.get("time", "")[:19], r.get("command", ""), r.get("detail", ""))
    console.print(t)


@app.command("list")
def list_projects():
    projects = store.list_projects()
    if not projects:
        console.print("[yellow]暂无项目[/yellow]"); return
    active = store.get_active_project_id()
    t = Table(title="项目列表")
    t.add_column("", width=2)  # 活动标记列
    t.add_column("ID", style="cyan"); t.add_column("名称", style="bold"); t.add_column("创建时间")
    for p in projects:
        mark = "[green]*[/green]" if p["id"] == active else ""
        t.add_row(mark, p["id"], p["name"], p.get("created_at", "")[:19])
    console.print(t)


@app.command()
def info():
    project = _require_project()
    panels = store.load_panels(project["id"])
    ents = store.load_entities(project["id"])
    c = sum(1 for e in ents if e.get("entity_type") == "character")
    l = sum(1 for e in ents if e.get("entity_type") == "location")
    i = sum(1 for e in ents if e.get("entity_type") == "item")
    console.print(RichPanel(f"{project['name']} ({project['id']})\n分镜:{len(panels)} 人物:{c} 场景:{l} 道具:{i}", title="项目信息"))


# ── 小说管理 ──

novel_app = typer.Typer(help="小说管理")


@novel_app.command("import")
def novel_import(file: str):
    """导入小说文件"""
    path = Path(file)
    if not path.exists():
        console.print(f"[red]不存在: {file}[/red]"); raise typer.Exit(1)
    text = path.read_text(encoding="utf-8")
    project = _require_project()
    project["source_text"] = text
    store.save_project(project)
    _commit_and_log(project["id"], "import", f"{path.name} ({len(text)}字)")
    console.print(f"[green]{len(text):,} 字[/green]")


@novel_app.command("episodes")
def novel_episodes(show: int = typer.Option(-1, help="显示某集内容，-1只显示列表")):
    """查看分集列表"""
    project = _require_project()
    eps = store.load_episodes(project["id"])
    if not eps:
        console.print("[yellow]暂无分集，请先: drama novel split[/yellow]"); return
    if show >= 0:
        tgt = next((e for e in eps if e.get("index") == show), None)
        if not tgt:
            console.print(f"[red]index {show} 不存在[/red]"); raise typer.Exit(1)
        console.print(RichPanel(tgt.get("content", ""), title=f"[{show}] {tgt.get('title','')}"))
        return
    t = Table(title=f"分集 - {project['name']}")
    t.add_column("index", style="cyan", width=6)
    t.add_column("标题", style="bold")
    t.add_column("字数", width=8)
    t.add_column("摘要", max_width=40)
    for e in eps:
        t.add_row(str(e.get("index","")), e.get("title",""), str(e.get("char_count","")), e.get("summary",""))
    console.print(t)


@novel_app.command("import-episodes")
def novel_import_episodes(
    folder: str = typer.Option(..., help="存放分集文本文件的文件夹"),
    outline: str = typer.Option("", help="可选：大纲文件路径，作为 index=0"),
    pattern: str = typer.Option("*.txt", help="文件匹配模式，默认 *.txt"),
):
    """导入人工切好的分集文本 (跳过 AI 分集)

    适用于超长小说人工分集的场景：把切好的各集文本按文件名排序放在一个文件夹里，
    文件名建议带序号 (如 01-第一集.txt / 02-第二集.txt) 以保证顺序正确。
    每个文件成为一集，文件名(去扩展名)作为标题。
    """
    project = _require_project()
    pid = project["id"]
    folder_path = Path(folder)
    if not folder_path.is_dir():
        console.print(f"[red]文件夹不存在: {folder}[/red]"); raise typer.Exit(1)

    # 按文件名排序收集分集文件 (文件名带序号即可保证顺序)
    files = sorted(folder_path.glob(pattern))
    if not files:
        console.print(f"[red]文件夹内没有匹配 {pattern} 的文件[/red]"); raise typer.Exit(1)

    episodes = []
    # index=0 预留给大纲
    if outline:
        op = Path(outline)
        if not op.exists():
            console.print(f"[red]大纲文件不存在: {outline}[/red]"); raise typer.Exit(1)
        otext = op.read_text(encoding="utf-8")
        episodes.append({"index": 0, "title": "大纲", "summary": "",
                         "content": otext, "char_count": len(otext)})
    else:
        # 无大纲时也占住 index=0，内容留空，保持"1 起为正式分集"的约定
        episodes.append({"index": 0, "title": "大纲", "summary": "", "content": "", "char_count": 0})

    # 逐个文件导入为分集
    for i, f in enumerate(files, start=1):
        content = f.read_text(encoding="utf-8")
        episodes.append({
            "index": i,
            "title": f.stem,          # 文件名去扩展名作标题
            "summary": "",
            "content": content,
            "char_count": len(content),
        })
        console.print(f"  [{i}] {f.stem} ({len(content)}字)")

    store.save_episodes(pid, episodes)
    _commit_and_log(pid, "import-episodes", f"{len(files)}集")
    console.print(f"[green]已导入 {len(files)} 集[/green]")


@novel_app.command()
def convert(file: str = typer.Option(""), episode: int = typer.Option(-1, help="转换指定集 index，-1转换全部")):
    """AI转换分镜"""
    project = _require_project()
    eps = store.load_episodes(project["id"])
    # 有分集且未指定文件时，按集转换（跳过 index=0 大纲）
    if eps and not file.strip():
        targets = [e for e in eps if e.get("index", 0) > 0]
        if episode >= 0:
            targets = [e for e in targets if e.get("index") == episode]
        if not targets:
            console.print("[red]没有可转换的分集[/red]"); raise typer.Exit(1)
        from drama_manager.llm.nodes.convert import convert_novel_node
        outline_entry = next((e for e in eps if e.get("index") == 0), {})
        outline = outline_entry.get("content", "")
        all_panels = []
        for e in targets:
            idx = e["index"]
            prev_ep = next((x for x in eps if x.get("index") == idx - 1), None)
            next_ep = next((x for x in eps if x.get("index") == idx + 1), None)
            prev_summary = prev_ep.get("summary", "") if prev_ep and prev_ep.get("index", 0) > 0 else ""
            next_summary = next_ep.get("summary", "") if next_ep else ""
            console.print(f"[cyan]转换 [{idx}] {e['title']}...[/cyan]")
            state = {
                "project_id": project["id"],
                "raw_text": e.get("content", ""),
                "outline": outline,
                "prev_summary": prev_summary,
                "next_summary": next_summary,
                "style": "",  # 留空，由项目 prompts.py 的 STYLE 决定
                "panels": [], "entities": [], "panel_entity_bindings": {},
                "variables": {}, "messages": [], "error": None,
            }
            result = asyncio.run(convert_novel_node(state))
            ep_panels = result.get("panels", [])
            for p in ep_panels:
                p["episode_index"] = idx
                p["episode_title"] = e.get("title", "")
            all_panels.extend(ep_panels)
        for i, p in enumerate(all_panels):
            p["sort_order"] = i + 1
        store.add_panels_batch(project["id"], all_panels)
        _commit_and_log(project["id"], "convert", f"{len(all_panels)}分镜")
        console.print(f"[green]{len(all_panels)} 分镜[/green]")
        return
    raw = file.strip() or project.get("source_text", "")
    if not raw:
        console.print("[red]请先导入小说或运行 novel split[/red]"); raise typer.Exit(1)
    from drama_manager.llm.nodes.convert import convert_novel_node
    state = {"project_id": project["id"], "raw_text": raw, "panels": [], "entities": [],
             "panel_entity_bindings": {}, "variables": {}, "messages": [], "error": None}
    console.print("[cyan]转换中...[/cyan]")
    result = asyncio.run(convert_novel_node(state))
    panels = result.get("panels", [])
    if not panels:
        console.print("[red]失败[/red]"); raise typer.Exit(1)
    store.add_panels_batch(project["id"], panels)
    _commit_and_log(project["id"], "convert", f"{len(panels)}分镜")
    console.print(f"[green]{len(panels)} 分镜[/green]")


@novel_app.command("split")
def novel_split(file: str = typer.Option(...), max_chars: int = typer.Option(300000, help="字数硬上限，超过则中止")):
    """交互式分集（全文喂 LLM，需长上下文模型；超过上限中止）"""
    project = _require_project()
    console.print(f"[yellow]文件参数: {repr(file)}[/yellow]")
    try:
        text = Path(file).read_text(encoding="utf-8")
    except Exception as e:
        console.print(f"[red]文件读取失败: {file}[/red]")
        console.print(f"[red]错误: {e}[/red]")
        raise typer.Exit(1)
    if not text:
        console.print("[red]文件为空[/red]"); raise typer.Exit(1)

    pid = project["id"]
    # 分集过程的控制台步骤打印 (最终结果落盘到统一日志 operations.jsonl)
    def log(step, status, detail=""):
        icon = {"start": ">>", "ok": "OK", "info": "..", "error": "!!"}.get(status, "..")
        console.print(f"  {icon} [{step}] {detail}")

    log("init", "start", f"{len(text)}字, 上限{max_chars}")
    # 硬上限: 超过则中止 (全文喂模式下，过长会超模型上下文)
    if len(text) > max_chars:
        console.print(f"[red]文本过长 ({len(text)}字 > 上限{max_chars}字)，已中止。[/red]")
        console.print("[yellow]请手动切分后用 drama novel import-episodes 导入。[/yellow]")
        raise typer.Exit(1)

    from drama_manager.llm.nodes.split import generate_outline, generate_proposal, adjust_proposal, execute_split

    # 检测已缓存的大纲 (上次跑过 outline 但中途失败时会留下)，询问是否复用，避免重复花钱
    cached_outline = ""
    for v in store.load_variables(pid):
        if v.get("category") == "split" and v.get("key") == "outline":
            cached_outline = v.get("value", "")
            break

    outline = ""
    if cached_outline:
        console.print(RichPanel(cached_outline, title="已有大纲 (上次生成)", border_style="blue"))
        ans = input("  检测到已生成的大纲，是否复用？(Y 复用 / n 重新生成): ").strip().lower()
        if ans != "n":
            outline = cached_outline
            log("outline", "ok", f"复用缓存 {len(outline)}字")

    if not outline:
        log("outline", "start", "生成大纲...")
        try:
            outline = asyncio.run(generate_outline(text, pid))
            log("outline", "ok", f"{len(outline)}字")
        except Exception as e:
            log("outline", "error", str(e)); console.print(f"[red]大纲失败: {e}[/red]"); return
        console.print(RichPanel(outline, title="大纲", border_style="blue"))
        # 立即缓存大纲，后续步骤失败重跑时可复用，不必重新花钱生成
        store.set_variable(pid, "split", "outline", outline)

    log("proposal", "start", "生成方案...")
    try:
        proposal = asyncio.run(generate_proposal(outline, len(text), pid))
        log("proposal", "ok", f"{len(proposal)}字")
    except Exception as e:
        log("proposal", "error", str(e)); console.print(f"[red]方案失败: {e}[/red]"); return
    console.print(RichPanel(proposal, title="方案", border_style="green"))

    confirmed = "[CONFIRMED]" in proposal
    if confirmed:
        proposal = proposal.replace("[CONFIRMED]", "").strip()
        log("confirm", "ok", "AI直接确认")

    rnd = 0
    while not confirmed:
        rnd += 1
        fb = input(f"  [第{rnd}轮反馈]: ").strip()
        if not fb: continue
        log(f"fb#{rnd}", "info", fb)
        try:
            proposal = asyncio.run(adjust_proposal(outline, proposal, fb, pid))
            if "[CONFIRMED]" in proposal:
                proposal = proposal.replace("[CONFIRMED]", "").strip()
                confirmed = True
                log("adjust", "ok", "定稿")
            else:
                log("adjust", "ok", "已调整")
        except Exception as e:
            log("adjust", "error", str(e)); console.print(f"[red]{e}[/red]"); continue
        console.print(RichPanel(proposal, title=f"调整 (第{rnd}轮)", border_style="green"))

    log("execute", "start", "执行分段...")
    try:
        eps = asyncio.run(execute_split(outline, proposal, text, pid))
        log("execute", "ok", f"{len(eps)}段")
    except Exception as e:
        log("execute", "error", str(e)); console.print(f"[red]{e}[/red]"); return
    for ep in eps:
        log("ep", "info", f"[{ep.get('index',0)}] {ep.get('title','')} ({ep.get('char_count',0)}字)")

    # 大纲与分集统一存入 episodes.json: index=0 为大纲，1 起为正式分集
    outline_entry = {"index": 0, "title": "大纲", "summary": "", "content": outline, "char_count": len(outline)}
    for ep in eps:
        ep["index"] = ep["index"] + 1
    store.save_episodes(pid, [outline_entry] + eps)
    store.set_variable(pid, "split", "proposal", proposal)
    # 大纲已正式存入 episodes.json[0]，清空临时缓存，避免下次误复用
    store.set_variable(pid, "split", "outline", "")

    # 统一日志: 记录分集结果 + 经过的轮次
    _commit_and_log(pid, "split", f"{len(eps)}段 (交互{rnd}轮)")
    log("done", "ok", "已保存")
    console.print(f"[green]{len(eps)}段已保存[/green]")


# ── 分镜管理 ──

panel_app = typer.Typer(help="分镜管理")


@panel_app.command("list")
def panel_list():
    project = _require_project()
    panels = store.load_panels(project["id"])
    t = Table(title=f"分镜 - {project['name']}")
    t.add_column("#", style="cyan", width=4)
    t.add_column("秒", width=3)
    t.add_column("场景", width=18)
    t.add_column("原文片段", max_width=40)
    t.add_column("提示词", width=6)
    for p in sorted(panels, key=lambda x: x.get("sort_order", 0)):
        src = p.get("source_text", "")
        src = (src[:38] + "...") if len(src) > 40 else src
        t.add_row(
            str(p.get("sort_order", "")),
            str(p.get("duration", "")),
            p.get("scene_info", ""),
            src,
            "Y" if p.get("prompt") else "N",
        )
    console.print(t)


@panel_app.command("show")
def panel_show(index: int):
    project = _require_project()
    panels = store.load_panels(project["id"])
    tgt = next((p for p in panels if p.get("sort_order") == index), None)
    if not tgt:
        console.print(f"[red]#{index}不存在[/red]"); raise typer.Exit(1)
    ents = store.get_panel_entities(project["id"], tgt["id"])
    e_txt = ", ".join(e["name"] for e in ents) or "None"
    console.print(RichPanel(
        f"#{tgt.get('sort_order')}  时长:{tgt.get('duration','?')}秒  场景:{tgt.get('scene_info','')}\n\n"
        f"原文片段:\n{tgt.get('source_text','')}\n\n"
        f"图片提示词:\n{tgt.get('prompt','') or '(空)'}\n\n"
        f"视频提示词:\n{tgt.get('video_prompt','') or '(空)'}\n\n"
        f"绑定: {e_txt}", title="分镜"))


@panel_app.command("edit")
def panel_edit(index: int, field: str = typer.Option(...), value: str = typer.Option(...)):
    project = _require_project()
    panels = store.load_panels(project["id"])
    tgt = next((p for p in panels if p.get("sort_order") == index), None)
    if not tgt:
        console.print(f"[red]#{index}不存在[/red]"); raise typer.Exit(1)
    store.update_panel(project["id"], tgt["id"], {field: value})
    _commit_and_log(project["id"], "edit", f"#{index} {field}")
    console.print(f"[green]#{index} {field} OK[/green]")


@panel_app.command("add")
def panel_add(paperwork: str = typer.Option(...)):
    project = _require_project()
    panels = store.load_panels(project["id"])
    nxt = max((p.get("sort_order", 0) for p in panels), default=0) + 1
    store.add_panel(project["id"], {"sort_order": nxt, "paperwork": paperwork})
    _commit_and_log(project["id"], "add", f"#{nxt}")
    console.print(f"[green]#{nxt} OK[/green]")


@panel_app.command("delete")
def panel_delete(index: int):
    project = _require_project()
    panels = store.load_panels(project["id"])
    tgt = next((p for p in panels if p.get("sort_order") == index), None)
    if not tgt:
        console.print(f"[red]#{index}不存在[/red]"); raise typer.Exit(1)
    store.delete_panel(project["id"], tgt["id"])
    _commit_and_log(project["id"], "delete", f"#{index}")
    console.print(f"[green]#{index} deleted[/green]")


# ── 实体管理 ──

entity_app = typer.Typer(help="实体管理")


@entity_app.command("list")
def entity_list(type: str = typer.Option("")):
    project = _require_project()
    ents = store.load_entities(project["id"], entity_type=type or None)
    t = Table(title=f"实体 - {project['name']}")
    t.add_column("类型"); t.add_column("名称", style="bold"); t.add_column("别名"); t.add_column("描述", max_width=30)
    for e in ents:
        d = (e.get("description", "")[:28] + "...") if len(e.get("description", "")) > 30 else e.get("description", "")
        t.add_row(e.get("entity_type", ""), e.get("name", ""), e.get("aliases", ""), d)
    console.print(t)


@entity_app.command("show")
def entity_show(name: str):
    project = _require_project()
    e = store.find_entity_by_name(project["id"], name)
    if not e:
        console.print(f"[red]'{name}'不存在[/red]"); raise typer.Exit(1)
    panels = store.get_entity_panels(project["id"], e["id"])
    p_txt = ", ".join(f"#{p.get('sort_order')}" for p in panels) or "None"
    console.print(RichPanel(f"{e['name']} ({e.get('entity_type','')})\n别名: {e.get('aliases','') or 'None'}\n描述: {e.get('description','')}\n分镜: {p_txt}", title="实体"))


@entity_app.command("add")
def entity_add(name: str, type: str = typer.Option("character"), description: str = typer.Option(""), aliases: str = typer.Option(""), importance: str = typer.Option("major")):
    project = _require_project()
    store.add_entities_batch(project["id"], [{"entity_type": type, "name": name, "aliases": aliases, "description": description, "importance": importance}])
    _commit_and_log(project["id"], "entity-add", f"{type} '{name}'")
    console.print(f"[green]{type}: {name} ({importance})[/green]")


@entity_app.command("edit")
def entity_edit(name: str, field: str = typer.Option(...), value: str = typer.Option(...)):
    """编辑实体字段 (description/aliases/importance)"""
    project = _require_project()
    e = store.find_entity_by_name(project["id"], name)
    if not e:
        console.print(f"[red]'{name}' 不存在[/red]"); raise typer.Exit(1)
    entities = store.load_entities(project["id"])
    for ent in entities:
        if ent.get("id") == e["id"]:
            ent[field] = value
            break
    store.save_entities(project["id"], entities)
    _commit_and_log(project["id"], "entity-edit", f"'{name}' {field}")
    console.print(f"[green]{name}.{field} = {value}[/green]")


@entity_app.command("set-media")
def entity_set_media(name: str, image: str = typer.Option(""), audio: str = typer.Option("")):
    """绑定实体的参考图片或音频路径"""
    project = _require_project()
    e = store.find_entity_by_name(project["id"], name)
    if not e:
        console.print(f"[red]'{name}' 不存在[/red]"); raise typer.Exit(1)
    updates = {}
    if image:
        path = Path(image)
        if not path.exists():
            console.print(f"[red]图片不存在: {image}[/red]"); raise typer.Exit(1)
        updates["image_path"] = str(path.resolve())
    if audio:
        path = Path(audio)
        if not path.exists():
            console.print(f"[red]音频不存在: {audio}[/red]"); raise typer.Exit(1)
        updates["audio_path"] = str(path.resolve())
    if not updates:
        console.print("[yellow]请指定 --image 或 --audio[/yellow]"); return
    entities = store.load_entities(project["id"])
    for ent in entities:
        if ent.get("id") == e["id"]:
            ent.update(updates)
            break
    store.save_entities(project["id"], entities)
    _commit_and_log(project["id"], "set-media", f"'{name}'")
    for k, v in updates.items():
        console.print(f"[green]{name}.{k} = {v}[/green]")


@entity_app.command("extract")
def entity_extract(
    episode: int = typer.Option(-1, help="只提取指定集 index 的实体，-1=全部分镜"),
    replace: bool = typer.Option(False, help="清空现有实体重新提取，默认增量去重"),
):
    project = _require_project()
    panels = store.load_panels(project["id"])
    if not panels:
        console.print("[red]没有分镜[/red]"); raise typer.Exit(1)
    # 按集过滤 (只提取该集分镜的实体)
    if episode >= 0:
        panels = [p for p in panels if p.get("episode_index") == episode]
        if not panels:
            console.print(f"[red]第{episode}集没有分镜[/red]"); raise typer.Exit(1)
    if replace:
        store.save_entities(project["id"], [])
        store.save_bindings(project["id"], {})
        console.print("[yellow]已清空旧实体与绑定[/yellow]")
    existing = store.load_entities(project["id"])
    existing_names = {e.get("name", "") for e in existing}
    pd = [{"sort_order": p.get("sort_order", 0), "scene": p.get("paperwork", ""), "action": "", "dialogue": p.get("dialogue", "")} for p in panels]
    from drama_manager.llm.nodes.extract import extract_entities_node
    state = {"project_id": project["id"], "raw_text": "", "panels": pd, "entities": existing, "panel_entity_bindings": {}, "variables": {}, "messages": [], "error": None}
    scope = f"第{episode}集" if episode >= 0 else "全部"
    console.print(f"[cyan]提取中 ({scope}, {len(pd)}个分镜)...[/cyan]")
    result = asyncio.run(extract_entities_node(state))
    ents = result.get("entities", [])
    # 按 name 去重，跳过已存在的同名实体
    new_ents = [e for e in ents if e.get("name", "") not in existing_names]
    skipped = len(ents) - len(new_ents)
    store.add_entities_batch(project["id"], new_ents)
    _commit_and_log(project["id"], "extract", f"+{len(new_ents)}实体")
    msg = f"{len(new_ents)} 新实体"
    if skipped:
        msg += f"（跳过 {skipped} 个重复）"
    console.print(f"[green]{msg}[/green]")


@entity_app.command("bind")
def entity_bind(episode: int = typer.Option(-1, help="指定集 index，-1=全部；按集调用 LLM 精确绑定")):
    """将实体与分镜进行 LLM 精确绑定"""
    project = _require_project()
    panels = store.load_panels(project["id"])
    entities = store.load_entities(project["id"])
    if not panels:
        console.print("[red]没有分镜[/red]"); raise typer.Exit(1)
    if not entities:
        console.print("[red]没有实体，请先: drama entity extract[/red]"); raise typer.Exit(1)

    from drama_manager.llm.nodes.bind import bind_entities_llm

    # 按集分组
    if episode >= 0:
        ep_panels = [p for p in panels if p.get("episode_index") == episode]
        if not ep_panels:
            console.print(f"[red]第{episode}集没有分镜[/red]"); raise typer.Exit(1)
        groups = {episode: ep_panels}
    else:
        groups: dict[int, list] = {}
        for p in panels:
            ei = p.get("episode_index", 0)
            groups.setdefault(ei, []).append(p)

    existing = store.load_bindings(project["id"])
    pmap = {p["id"]: p for p in panels}
    emap = {str(i): e["id"] for i, e in enumerate(entities)}

    total_bound = 0
    for ei, ep_panels in sorted(groups.items()):
        console.print(f"[cyan]绑定第{ei}集 ({len(ep_panels)}个分镜)...[/cyan]")
        # LLM 返回 {sort_order_str: [entity_index_str, ...]}
        so_bindings = asyncio.run(bind_entities_llm(ep_panels, entities, project["id"]))
        # 转成 {panel_id: [entity_id, ...]}
        so_map = {str(p.get("sort_order")): p["id"] for p in ep_panels}
        for so, idxs in so_bindings.items():
            pid = so_map.get(so)
            if pid:
                existing[pid] = [emap[i] for i in idxs if i in emap]
                if existing[pid]:
                    total_bound += 1

    store.save_bindings(project["id"], existing)
    _commit_and_log(project["id"], "bind", f"{total_bound}分镜有绑定")
    console.print(f"[green]{total_bound}/{len(panels)} 分镜已绑定实体[/green]")


# ── 提示词 ──

prompt_app = typer.Typer(help="提示词")


@prompt_app.command("infer")
def prompt_infer(
    episode: int = typer.Option(-1, help="只推理指定集 index 的分镜，-1=不按集过滤"),
    panel_index: int = typer.Option(0, help="指定分镜序号，0=全部"),
    range_: str = typer.Option("", "--range", help="分镜序号区间，如 1-30（按 sort_order）"),
    only_empty: bool = typer.Option(False, help="只推理还没有提示词的分镜（断点续跑）"),
):
    project = _require_project()
    panels = store.load_panels(project["id"])
    if not panels:
        console.print("[red]没有分镜[/red]"); raise typer.Exit(1)
    # 按集过滤 (优先)
    if episode >= 0:
        panels = [p for p in panels if p.get("episode_index") == episode]
        if not panels:
            console.print(f"[red]第{episode}集没有分镜[/red]"); raise typer.Exit(1)
    # 按单个分镜序号过滤
    elif panel_index > 0:
        panels = [p for p in panels if p.get("sort_order") == panel_index]
        if not panels:
            console.print(f"[red]#{panel_index} 不存在[/red]"); raise typer.Exit(1)
    # 按序号区间过滤 (如 1-30)，可与 episode 叠加
    if range_.strip():
        try:
            lo, hi = (int(x) for x in range_.split("-"))
        except ValueError:
            console.print(f"[red]区间格式错误: {range_}（应如 1-30）[/red]"); raise typer.Exit(1)
        panels = [p for p in panels if lo <= p.get("sort_order", 0) <= hi]
        if not panels:
            console.print(f"[red]区间 {range_} 内无分镜[/red]"); raise typer.Exit(1)
    # 只推理还没生成提示词的分镜 (断点续跑，避免重复花钱)
    if only_empty:
        panels = [p for p in panels if not p.get("prompt")]
        if not panels:
            console.print("[green]该范围内所有分镜都已有提示词[/green]"); return
    ents = store.load_entities(project["id"])
    bindings = store.load_bindings(project["id"])
    variables = {v["key"]: v["value"] for v in store.load_variables(project["id"])}
    pd = [{"sort_order": p.get("sort_order", 0), "paperwork": p.get("paperwork", ""), "scene": "", "action": "", "dialogue": p.get("dialogue", "")} for p in panels]
    ed = [{"name": e.get("name", ""), "entity_type": e.get("entity_type", ""),
           "description": e.get("description", ""), "importance": e.get("importance", "major"),
           "image_path": e.get("image_path", "")} for e in ents]
    all_panels_full = store.load_panels(project["id"])
    pmap = {p.get("sort_order"): p["id"] for p in all_panels_full}
    emap = {e["id"]: str(i) for i, e in enumerate(ents)}
    bc = {}
    for pid, eids in bindings.items():
        so = next((s for s, p2 in pmap.items() if p2 == pid), None)
        if so is not None:
            bc[str(so)] = [emap[eid] for eid in eids if eid in emap]
    from drama_manager.llm.nodes.infer import infer_prompts_node
    state = {"project_id": project["id"], "raw_text": "", "panels": pd, "entities": ed, "panel_entity_bindings": bc, "variables": variables, "messages": [], "error": None}
    console.print(f"[cyan]推理 {len(pd)} 个分镜...[/cyan]")
    result = asyncio.run(infer_prompts_node(state))
    updated = result.get("panels", [])
    pmap2 = {p.get("sort_order"): p for p in all_panels_full}
    for u in updated:
        o = u.get("sort_order")
        if o in pmap2:
            store.update_panel(project["id"], pmap2[o]["id"], {"prompt": u.get("prompt", ""), "video_prompt": u.get("video_prompt", "")})
    _commit_and_log(project["id"], "infer", f"{len(updated)}分镜")
    console.print(f"[green]{len(updated)} 分镜[/green]")


# ── 变量 ──

variable_app = typer.Typer(help="变量管理")


@variable_app.command("list")
def variable_list():
    project = _require_project()
    vs = store.load_variables(project["id"])
    t = Table(title="变量")
    t.add_column("分类", style="cyan"); t.add_column("键", style="bold"); t.add_column("值")
    for v in vs:
        t.add_row(v.get("category", ""), v.get("key", ""), v.get("value", ""))
    console.print(t)


@variable_app.command("set")
def variable_set(key: str, value: str, category: str = typer.Option("custom")):
    project = _require_project()
    store.set_variable(project["id"], category, key, value)
    console.print(f"[green]{category}.{key} = {value}[/green]")


@variable_app.command("get")
def variable_get(key: str):
    project = _require_project()
    for v in store.load_variables(project["id"]):
        if v.get("key") == key:
            print(f"{v['category']}.{v['key']} = {v['value']}"); return
    console.print(f"[yellow]'{key}'不存在[/yellow]")


# ── Agent ──

@app.command()
def agent_run(file: str = typer.Option(""), threshold: int = typer.Option(300000)):
    """一键全流程"""
    project = _require_project()
    raw = file.strip() or project.get("source_text", "")
    if not raw:
        console.print("[red]请先导入小说[/red]"); raise typer.Exit(1)
    from drama_manager.llm.graph import build_drama_graph
    graph = build_drama_graph()
    state = {"project_id": project["id"], "raw_text": raw, "char_threshold": threshold,
             "is_append": False, "existing_outline": "", "existing_episodes": [], "split_rules": "",
             "outline": "", "episodes": [], "current_episode_index": 0,
             "panels": [], "episode_panel_map": {}, "entities": [], "panel_entity_bindings": {},
             "variables": {}, "messages": [], "error": None}  # style 由项目 prompts.py 的 STYLE 决定
    console.print("[cyan]运行中...[/cyan]")
    final = asyncio.run(graph.ainvoke(state))
    panels = final.get("panels", [])
    store.add_panels_batch(project["id"], panels)
    ents = final.get("entities", [])
    store.add_entities_batch(project["id"], ents)
    bindings = final.get("panel_entity_bindings", {})
    pim = {str(p.get("sort_order")): p["id"] for p in store.load_panels(project["id"])}
    eim = {str(i): e["id"] for i, e in enumerate(store.load_entities(project["id"]))}
    cb = {}
    for ss, il in bindings.items():
        pid = pim.get(ss)
        if pid: cb[pid] = [eim[idx] for idx in il if idx in eim]
    store.save_bindings(project["id"], cb)
    _commit_and_log(project["id"], "agent", f"{len(panels)}分镜 {len(ents)}实体")
    console.print(RichPanel(f"完成\n分镜:{len(panels)} 实体:{len(ents)}", title="OK", border_style="green"))


# ── Git ──

git_app = typer.Typer(help="Git版本管理")


@git_app.command("log")
def git_log(n: int = typer.Option(20)):
    project = _require_project()
    commits = _get_vcs(project["id"]).log(n)
    t = Table(title="版本历史")
    t.add_column("Hash", style="cyan", width=10); t.add_column("时间"); t.add_column("信息", style="bold")
    for c in commits:
        t.add_row(c["hash"][:8], c["date"][:19], c["message"])
    console.print(t)


@git_app.command("diff")
def git_diff(commit: str = typer.Option("HEAD~1")):
    project = _require_project()
    d = _get_vcs(project["id"]).diff(commit)
    print(d if d else "无差异")


@git_app.command("revert")
def git_revert(commit: str = typer.Argument(...)):
    project = _require_project()
    _get_vcs(project["id"]).checkout_all(commit)
    _commit_and_log(project["id"], "revert", f"{commit[:8]}")
    console.print(f"[green]回滚到 {commit[:8]}[/green]")


# ── 导出 ──

@app.command()
def export(
    out_dir: str = typer.Option("", help="导出目录，默认项目目录下的 export/"),
    fmt: str = typer.Option("jsonl", help="格式: jsonl(带序号,推荐) 或 txt(每行一条)"),
):
    """导出图片/视频提示词为分开的文件，分别供不同服务端使用

    图片提示词 → image_prompts.{jsonl|txt}
    视频提示词 → video_prompts.{jsonl|txt}
    两类提示词分别独立成文件，便于喂给不同的生图/生视频服务。
    jsonl 每条带 sort_order，方便服务端按分镜序号对应回填。
    """
    import json as _json
    from drama_manager.config import get_projects_dir
    project = _require_project()
    pid = project["id"]
    panels = sorted(store.load_panels(pid), key=lambda x: x.get("sort_order", 0))
    if not panels:
        console.print("[red]没有分镜[/red]"); raise typer.Exit(1)

    # 默认导出到 项目目录/export/
    target = Path(out_dir) if out_dir else (get_projects_dir() / pid / "export")
    target.mkdir(parents=True, exist_ok=True)

    img_file = target / f"image_prompts.{fmt}"
    vid_file = target / f"video_prompts.{fmt}"

    img_n = vid_n = 0
    if fmt == "jsonl":
        # JSONL: 每行 {sort_order, prompt}，服务端可按序号回填
        with open(img_file, "w", encoding="utf-8") as fi, open(vid_file, "w", encoding="utf-8") as fv:
            for p in panels:
                so = p.get("sort_order", 0)
                if p.get("prompt"):
                    fi.write(_json.dumps({"sort_order": so, "prompt": p["prompt"]}, ensure_ascii=False) + "\n")
                    img_n += 1
                if p.get("video_prompt"):
                    fv.write(_json.dumps({"sort_order": so, "prompt": p["video_prompt"]}, ensure_ascii=False) + "\n")
                    vid_n += 1
    elif fmt == "txt":
        # TXT: 每行一条提示词，纯净文本
        with open(img_file, "w", encoding="utf-8") as fi, open(vid_file, "w", encoding="utf-8") as fv:
            for p in panels:
                if p.get("prompt"):
                    fi.write(p["prompt"].replace("\n", " ") + "\n"); img_n += 1
                if p.get("video_prompt"):
                    fv.write(p["video_prompt"].replace("\n", " ") + "\n"); vid_n += 1
    else:
        console.print(f"[red]不支持的格式: {fmt}（用 jsonl 或 txt）[/red]"); raise typer.Exit(1)

    _commit_and_log(pid, "export", f"图{img_n}条/视频{vid_n}条 ({fmt})")
    console.print(RichPanel(
        f"图片提示词: {img_n} 条 → {img_file}\n"
        f"视频提示词: {vid_n} 条 → {vid_file}",
        title="导出完成", border_style="green"))


# ── 注册子应用 ──

app.add_typer(novel_app, name="novel")
app.add_typer(panel_app, name="panel")
app.add_typer(entity_app, name="entity")
app.add_typer(prompt_app, name="prompt")
app.add_typer(variable_app, name="variable")
app.add_typer(git_app, name="git")

if __name__ == "__main__":
    app()
