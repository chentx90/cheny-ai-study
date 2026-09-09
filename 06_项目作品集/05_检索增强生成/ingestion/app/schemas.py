"""数据模型定义（Pydantic）。

定义了这条流水线中被传递的核心数据结构，包括：
- Chunk：文本分块，是向量化与检索的最小单元
- Document：一个待解析/已解析的文档，包含标题、元数据和 Chunk 列表
- Asset / DataAsset：媒体资产（图片、视频）和结构化数据资产
- LoadedDocument / RawPage：加载器产出的中间格式，承载分页/分节文本
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class Chunk(BaseModel):
    """文本分块，是向量化和语义检索的基本单元。

    每个 Chunk 代表文档中一段语义连续、长度适中的文本切片。
    同时携带上下文信息（标题路径、位置、摘要、预设问题），
    用于提升检索质量和 LLM 生成时的引用体验。
    """

    section_path: str
    """章节路径，如 "第一章 > 1.1 液压系统"。
    记录该 Chunk 在原始文档中的层级位置，用于过滤和排序。"""

    title_context: str
    """标题上下文，通常是文档顶层标题或当前章节标题。
    与 section_path 配合为 Chunk 提供完整的文档位置信息。"""

    content: str
    """该 Chunk 的原始正文内容（纯文本）。"""

    summary: str
    """该 Chunk 的自动摘要（通常取前 2 句或前 200 字符）。
    用于检索时的高层摘要展示，以及 embedding 拼接时增强语义密度。"""

    preset_questions: List[str] = Field(default_factory=list)
    """针对此 Chunk 内容的预设问题列表。
    由规则引擎（Chunker._generate_preset_questions）或 LLM 富化生成，
    用于在检索结果中推荐相关问题、提升检索命中率。"""

    physical_context: Optional[Dict[str, Any]] = None
    """物理上下文，记录 Chunk 在原始文件中的位置信息。
    示例：{"page": 5, "slide": 3, "sheet": "Sheet1", "row": 12}
    用于在展示层精确定位原文出处。"""

    def build_embedding_text(self) -> str:
        """拼接该 Chunk 用于生成 embedding 的文本。

        策略是将最有利于语义检索的字段用分隔符拼接在一起，
        形成一段富含上下文信息的文本，再交由 Embedding 模型编码。
        字段顺序反映了对检索效果的重要性权重。

        Returns:
            包含标题、路径、摘要、正文和预设问题的拼接字符串。
        """
        parts = [
            f"[Title Context] {self.title_context}",
            f"[Section Path] {self.section_path}",
            f"[Summary] {self.summary}",
            f"[Content] {self.content}",
            f"[Preset Questions] {' '.join(self.preset_questions)}"
        ]
        return "\n".join(parts)


class Asset(BaseModel):
    """通用媒体资产（非结构化）。"""

    asset_type: str
    """资产类型，如 "image"、"video"、"audio"。"""

    asset_url: str
    """资产的 URL 或文件路径。"""

    caption: Optional[str]
    """对人可读的简短说明或标题。"""

    ocr_text: Optional[str]
    """若资产为图片或扫描件，经过 OCR 提取的文字内容。"""

    description: Optional[str]
    """更详细的自然语言描述（可由描述模型或人工标注生成）。"""

    physical_context: Optional[Dict[str, Any]] = None
    """物理上下文，记录该资产在原始文档中的位置。"""


class DataAsset(BaseModel):
    """结构化数据资产，用于描述表格、指标、关联关系等。

    典型来源是 Excel 文件中的固定 sheet（tables、columns、metrics 等），
    也可以是手工标注或知识图谱提取的结构化描述。
    """

    asset_type: str
    """资产类型，如 "table"、"column"、"metric"、"case"、"tool"。"""

    name: str
    """资产的标准名称（通常为设计文档中的命名）。"""

    description: str
    """对资产用途、含义的自然语言描述。"""

    business_domain: str
    """所属业务领域，用于跨资产检索时的领域过滤。"""

    parent_name: Optional[str]
    """父级资产名称（如某列所属表、某指标所属表）。"""

    synonyms: List[str] = Field(default_factory=list)
    """同义词或别名字段，用于召回时的术语匹配和扩展。"""

    formula: Optional[str]
    """若是度量指标类资产，记录其计算公式或业务逻辑。"""

    related_table: Optional[str]
    """关联的数据库表名，用于建表/指标场景的联动检索。"""

    related_columns: List[str] = Field(default_factory=list)
    """关联的字段名列表。"""

    example_values: Optional[Dict[str, Any]] = None
    """示例值或 Mock 数据，用于表格类和指标类的展示和校验。"""


class Document(BaseModel):
    """文档模型，代表一个已解析或待入库的完整文档。"""

    title: str
    """文档标题，通常取自文件名或第一个主标题。"""

    doc_type: str
    """文档类型标识，如 "markdown"、"pdf"、"excel"、"manual"。"""

    source_uri: Optional[str]
    """原始文件路径或 URL，用于溯源和重新解析。"""

    business_domain: Optional[str]
    """所属业务领域，用于按领域隔离检索范围。"""

    version: Optional[str]
    """文档版本号，用于多版本文档的增量更新。"""

    status: str = "active"
    """文档状态，如 "active"（活跃）、"archived"（归档）。"""

    chunks: List[Chunk] = Field(default_factory=list)
    """由该文档解析出的全部 Chunk 列表。"""


class RawPage(BaseModel):
    """加载器产出的原始页/节数据。"""

    page_number: int
    """页码或节序号。"""

    text: str
    """该页/节的纯文本内容。"""

    metadata: Optional[Dict[str, Any]] = None
    """额外元信息，如 {"source": "...", "page_count": 10, "section_path": "..."}。"""


class LoadedDocument(BaseModel):
    """加载器产出的中间格式，承载分页/分节文本。"""

    title: str
    """文档标题。"""

    source_uri: Optional[str]
    """原始文件路径或 URL。"""

    doc_type: str
    """文档类型标识。"""

    business_domain: Optional[str]
    """所属业务领域。"""

    pages: List[RawPage]
    """原始页/节列表，由加载器逐页/逐节填充。"""