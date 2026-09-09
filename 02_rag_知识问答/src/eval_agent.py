"""
评测集生成 Agent（LangChain + LangGraph）

读取结构文本 md，用 LLM 自动生成多维度评测问题。

用法：
    cd <REPO_ROOT>\06_项目作品集\02_知识问答
    python -m src.eval_agent --max_files 5
    python -m src.eval_agent
    python -m src.eval_agent --reset
"""

# ============================================================
# 第 1 段：imports + 配置 + LLM 初始化
# ============================================================

# --- 库 ---
import json
import logging
import argparse
from pathlib import Path
from typing import TypedDict
from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from .prompt import QUESTION

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# --- 路径常量 ---
# 项目根目录（02_知识问答/）
PROJECT_ROOT = Path(__file__).parent.parent

# 输入：100 个结构文本 md
STRUCTURED_DIR = PROJECT_ROOT / "data" / "cleaned" / "3-结构文本"

# 输出：评测集 JSON
OUTPUT_FILE = PROJECT_ROOT / "data/cleaned/10-评测集" / "eval_questions.json"

# 断点续传进度文件
PROGRESS_FILE = PROJECT_ROOT / "data/cleaned/10-评测集" / "eval_progress.json"

# 文档截断长度（字符数）
MAX_DOC_CHARS = 5000


# --- LLM 初始化 ---
load_dotenv(PROJECT_ROOT.parent.parent / ".env")

BASE_URL = os.getenv("LLM_BASE_URL") + "/v1"
API_KEY = os.getenv("LLM_API_KEY")
MODEL = os.getenv("LLM_MODEL")
TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

llm = ChatOpenAI(
    base_url=BASE_URL,    # ← 你的 API 地址
    api_key=API_KEY,                       # ← 你的  key
    model=MODEL,              # ← 你当前用的模型
    temperature=0.4,                        # 低温保稳定
    max_retries=2,                          # LangChain 内置重试
    timeout=TIMEOUT
)


# ============================================================
# 第 2 段：Pydantic 数据模型
# ============================================================
# ← 你来写：EvalQuestion + DocEvalResult
# 参考任务计划里的第 2 段说明
class EvalQuestion(BaseModel):
    category: str = Field(description="问题类型：单跳事实性问题|多跳推理问题|否定/边界问题|数值/列表问题")
    question: str = Field(description="用户问句")
    ground_truth: str = Field(description="参考答案")
    source_segments: list[str] = Field(description="原文中支撑答案的片段")
    context_required: bool = Field(description="是否需要上下文才能回答")
    notes: str = Field(default="", description="额外说明（可选）")

class DocEvalResult(BaseModel):
    questions: list[EvalQuestion] = Field(description="该文档生成的评测问题列表")


# ============================================================
# 第 3 段：LangGraph State 定义
# ============================================================
class AgentState(TypedDict):
    doc_ids: list[str]   # 待处理文档列表
    current_idx: int   # 当前处理到第几个（索引）
    current_doc_id: str  # 当前正在处理文档的ID
    current_content: str # 当前文件的内容
    generated_questions: list[dict] #  当前文档生成的内容
    all_questions: list[dict] # 全部已生成问题，最终写入json
    completed: list[str] # 已完成文件ID列表（断点续传用）
    errors: list[str] # 错误记录


# ============================================================
# 第 4 段：节点函数
# ============================================================
# ← 你来写：load_doc / generate / validate / save
def load_doc(state: AgentState) -> dict:
    """
    根据
    doc_ids: list[str]   # 待处理文档列表
    current_idx: int   # 当前处理到第几个（索引）
    current_doc_id: str  # 当前正在处理文档的ID
    读取文件，返回
    current_content: str # 当前文件的内容
    """
    doc_id = state["doc_ids"][state["current_idx"]]
    md_path = STRUCTURED_DIR / f"{doc_id}.md"

    if not md_path.exists():
        logger.error(f"[{doc_id}] 文件不存在")
        return {
            "current_doc_id": doc_id,
            "current_content": "",
            "errors": state["errors"] + [f"{doc_id} 文件不存在"],
        }

    try:
        content = md_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"[{doc_id}] 读取失败: {e}")
        return {
            "current_doc_id": doc_id,
            "current_content": "",
            "errors": state["errors"] + [f"{doc_id} 读取失败: {e}"],
        }

    # 截断
    if len(content) > MAX_DOC_CHARS:
        content = content[:MAX_DOC_CHARS]

    return {
        "current_doc_id": doc_id,
        "current_content": content,
    }
def generate(state: AgentState) -> dict:
    """调 LLM 生成评测问题。"""
    doc_id = state["current_doc_id"]
    content = state["current_content"]

    if len(content) < 50:
        logger.warning(f"[{doc_id}] 内容过短，跳过")
        return {"generated_questions": []}

    message = [
        SystemMessage(content=QUESTION),
        HumanMessage(content=f"文档 ID: {doc_id}\n\n{content}")
    ]

    try:
        structured_llm = llm.with_structured_output(DocEvalResult, method="json_mode")
        result = structured_llm.invoke(message)

        questions = [q.model_dump() for q in result.questions]
        for q in questions:
            q["gold_doc_ids"] = [doc_id]
            q["current_idx"] = state["current_idx"] + 1

        logger.info(f"[{doc_id}] 生成 {len(questions)} 个问题")
        return {"generated_questions": questions}

    except Exception as e:
        logger.error(f"[{doc_id}] 生成失败: {e}")
        return {
            "generated_questions": [],
            "errors": state["errors"] + [f"{doc_id}: {str(e)}"],
        }

def validate(state: AgentState) -> dict:
    """校验生成结果。"""
    questions = state["generated_questions"]
    valid = [q for q in questions if len(q.get("question", "")) >= 10]
    if len(valid) < len(questions):
        logger.warning(f"过滤掉 {len(questions) - len(valid)} 个低质量问题")
    return {"generated_questions": valid}

def save(state: AgentState) -> dict:
    all_q = state["all_questions"] + state["generated_questions"]
    completed = state["completed"] + [state["current_doc_id"]]
    new_idx = state["current_idx"] + 1

    # 每 5 个文档写一次文件
    if new_idx % 5 == 0 or new_idx >= len(state["doc_ids"]):
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(
            json.dumps(all_q, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        PROGRESS_FILE.write_text(
            json.dumps({"completed": completed}, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"已保存 {len(all_q)} 个问题，进度 {new_idx}/{len(state['doc_ids'])}")

    return {
        "all_questions": all_q,
        "completed": completed,
        "current_idx": new_idx,
    }

# ============================================================
# 第 5 段：Graph 组装
# ============================================================
# ← 你来写：StateGraph + add_node + add_edge + conditional_edges
# 参考任务计划里的第 5 段说明
def should_continue(state: AgentState) -> str:
    """结束路由，判断是否还有下一个文档要处理。"""
    if state["current_idx"] < len(state["doc_ids"]):
        return "continue"
    return "end"

graph = StateGraph(AgentState)

graph.add_node("load_doc", load_doc)
graph.add_node("generate", generate)
graph.add_node("validate", validate)
graph.add_node("save", save)

graph.set_entry_point("load_doc")

graph.add_edge("load_doc", "generate")
graph.add_edge("generate", "validate")
graph.add_edge("validate", "save")

graph.add_conditional_edges("save",should_continue,{"continue": "load_doc","end": END})

app = graph.compile()
# ============================================================
# 第 6 段：主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="评测集生成Agent")
    parser.add_argument("--max_files", type=int, default=0, help="最多处理文件数（0=全部）")
    parser.add_argument("--reset", action="store_true", help="清除进度重新开始")
    args = parser.parse_args()

    doc_ids = sorted([
        f.stem for f in STRUCTURED_DIR.iterdir()
        if f.is_file() and f.suffix == ".md"
    ])
    logging.info(f"总文档数{len(doc_ids)}")

    # --- 断点续传 ---
    completed = []
    if not args.reset and PROGRESS_FILE.exists():
        progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        completed = progress.get("completed", [])
        logger.info(f"断点续传: 已完成 {len(completed)} 个")

    # 过滤掉已完成的
    pending = [d for d in doc_ids if d not in completed]
    if args.max_files > 0:
        pending = pending[:args.max_files]
    logger.info(f"本次待处理: {len(pending)} 个")

    if not pending:
        logger.info("无待处理文档，退出")
        return

    # --- 加载已有结果 ---
    all_questions = []
    if not args.reset and OUTPUT_FILE.exists():
        all_questions = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))

    # --- 构造初始 state ---
    initial_state: AgentState = {
        "doc_ids": pending,
        "current_idx": 0,
        "current_doc_id": "",
        "current_content": "",
        "generated_questions": [],
        "all_questions": all_questions,
        "completed": completed,
        "errors": [],
    }

    # --- 运行 Graph ---
    final_state = app.invoke(initial_state)

    # --- 最终保存 ---
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(final_state["all_questions"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    PROGRESS_FILE.write_text(
        json.dumps({"completed": final_state["completed"]}, ensure_ascii=False),
        encoding="utf-8",
    )

    # --- 统计 ---
    total_q = len(final_state["all_questions"])
    logger.info(f"完成。总问题数: {total_q}")

    # 维度分布
    categories = {}
    for q in final_state["all_questions"]:
        cat = q.get("category", "未分类")
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        logger.info(f"  {cat}: {count}")

    if final_state["errors"]:
        logger.warning(f"错误数: {len(final_state['errors'])}")
        for e in final_state["errors"][:10]:
            logger.warning(f"  {e}")

if __name__ == "__main__":
    main()
    pass