# AI视频创作管理工具 - TDD测试驱动开发规范

## TDD概述

### 什么是TDD

测试驱动开发(Test-Driven Development)是一种软件开发方法，要求在编写功能代码之前先编写测试代码。遵循"红-绿-重构"循环：

1. **红(Red)**: 编写一个失败的测试
2. **绿(Green)**: 编写最少的代码使测试通过
3. **重构(Refactor)**: 优化代码，保持测试通过

### TDD的价值

- **设计驱动**: 测试先行促使思考API设计和接口契约
- **快速反馈**: 及时发现缺陷，降低调试成本
- **重构信心**: 完善的测试保证重构不破坏功能
- **文档作用**: 测试即文档，展示功能如何使用
- **质量保证**: 高测试覆盖率提升代码质量

## 项目TDD目标

### 覆盖率目标

| 层级 | 目标覆盖率 | 说明 |
|------|-----------|------|
| 核心业务逻辑 | ≥90% | 文档处理、实体提取、提示词生成等 |
| 服务层 | ≥85% | API端点、业务服务类 |
| 工具类/辅助函数 | ≥80% | 通用工具、数据转换等 |
| UI组件 | ≥70% | 关键交互组件 |
| 整体项目 | ≥80% | 全项目代码覆盖率 |

### 测试金字塔

```
           ┌──────────┐
          /  E2E测试   \      10% - 端到端场景测试
         /    (慢)      \
        ├────────────────┤
       /   集成测试       \    30% - 模块间协作测试
      /    (中速)         \
     ├──────────────────────┤
    /      单元测试          \  60% - 函数级测试
   /       (快速)            \
  └──────────────────────────┘
```

## TDD工作流程

### 标准开发流程

```python
# 步骤1: 编写测试（红色阶段）
def test_split_document_by_chapter():
    """测试按章节切分文档"""
    # Arrange - 准备测试数据
    content = """
    # 第一章 开始
    这是第一章内容...
    
    # 第二章 发展
    这是第二章内容...
    """
    strategy = ChapterSplitStrategy()
    
    # Act - 执行被测试方法
    segments = strategy.split(content)
    
    # Assert - 验证结果
    assert len(segments) == 2
    assert "第一章" in segments[0]
    assert "第二章" in segments[1]

# 步骤2: 运行测试，确认失败（还没实现功能）
# $ pytest tests/test_document_processor.py::test_split_document_by_chapter
# FAILED - AttributeError: 'ChapterSplitStrategy' object has no attribute 'split'

# 步骤3: 实现最小功能代码（绿色阶段）
class ChapterSplitStrategy(SplitStrategy):
    def split(self, content: str) -> List[str]:
        # 最简单的实现，使其通过测试
        chapters = re.split(r'\n# 第\d+章', content)
        return [ch.strip() for ch in chapters if ch.strip()]

# 步骤4: 再次运行测试，确认通过
# $ pytest tests/test_document_processor.py::test_split_document_by_chapter
# PASSED

# 步骤5: 重构（如有需要）
class ChapterSplitStrategy(SplitStrategy):
    CHAPTER_PATTERN = re.compile(r'^#+\s*第\d+章', re.MULTILINE)
    
    def split(self, content: str) -> List[str]:
        # 重构：支持更多章节格式
        matches = list(self.CHAPTER_PATTERN.finditer(content))
        if not matches:
            return [content]
        
        segments = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i+1].start() if i+1 < len(matches) else len(content)
            segments.append(content[start:end].strip())
        
        return segments

# 步骤6: 测试仍然通过，重构成功
```

## 单元测试规范

### 测试文件组织

```
tests/
├── unit/                           # 单元测试
│   ├── test_document_processor.py  # 文档处理器测试
│   ├── test_entity_manager.py      # 实体管理器测试
│   ├── test_prompt_engine.py       # 提示词引擎测试
│   ├── test_video_generator.py     # 视频生成器测试
│   └── test_version_manager.py     # 版本管理器测试
├── integration/                    # 集成测试
│   ├── test_workflow_engine.py
│   └── test_api_endpoints.py
├── e2e/                            # 端到端测试
│   └── test_full_workflow.py
├── fixtures/                       # 测试数据
│   ├── sample_documents/
│   ├── sample_scripts/
│   └── sample_entities/
└── conftest.py                     # Pytest配置
```

### 命名规范

```python
# 测试类命名：Test + 被测试类名
class TestDocumentProcessor:
    pass

# 测试方法命名：test_<功能>_<场景>_<期望结果>
def test_split_document_by_chapter_returns_correct_segments():
    pass

def test_split_document_with_no_chapters_returns_single_segment():
    pass

def test_split_document_with_invalid_format_raises_error():
    pass
```

### AAA模式（Arrange-Act-Assert）

```python
def test_entity_extraction_with_valid_script():
    # Arrange - 准备测试数据和依赖
    script = Script(
        content="小明拿起宝剑，走进卧室。",
        segment_id="seg_001"
    )
    extractor = EntityExtractor()
    
    # Act - 执行被测试的操作
    entities = extractor.extract(script)
    
    # Assert - 验证结果
    assert len(entities) == 3
    assert any(e.name == "小明" and e.type == EntityType.CHARACTER for e in entities)
    assert any(e.name == "宝剑" and e.type == EntityType.PROP for e in entities)
    assert any(e.name == "卧室" and e.type == EntityType.SCENE for e in entities)
```

### 测试隔离原则

```python
import pytest
from unittest.mock import Mock, patch

class TestVideoGenerationEngine:
    @pytest.fixture
    def mock_api_client(self):
        """每个测试独立的mock对象"""
        client = Mock()
        client.generate.return_value = "task_123"
        return client
    
    @pytest.fixture
    def engine(self, mock_api_client):
        """每个测试独立的引擎实例"""
        return VideoGenerationEngine(api_client=mock_api_client)
    
    def test_generate_preview_calls_api_with_correct_params(self, engine, mock_api_client):
        # Arrange
        script = Script(content="测试剧本", duration=10)
        
        # Act
        task = engine.generate_preview(script, duration=4)
        
        # Assert
        mock_api_client.generate.assert_called_once()
        call_args = mock_api_client.generate.call_args
        assert call_args[1]['duration'] == 4
        assert task.task_id == "task_123"
```

## 核心模块测试用例

### 1. 文档处理器测试

```python
# tests/unit/test_document_processor.py
import pytest
from src.processors.document_processor import DocumentProcessor, ChapterSplitStrategy

class TestDocumentProcessor:
    """文档处理器单元测试"""
    
    @pytest.fixture
    def processor(self):
        return DocumentProcessor()
    
    @pytest.fixture
    def sample_novel(self):
        return """
        # 第一章 序幕
        这是第一章的内容，描述了故事的开始。
        小明是一个普通的少年。
        
        # 第二章 觉醒
        小明发现了自己的特殊能力。
        他开始了冒险之旅。
        """
    
    def test_load_document_with_txt_file(self, processor, tmp_path):
        """测试加载TXT文件"""
        # Arrange
        test_file = tmp_path / "test.txt"
        test_file.write_text("测试内容", encoding='utf-8')
        
        # Act
        doc = processor.load_document(str(test_file))
        
        # Assert
        assert doc.filename == "test.txt"
        assert doc.format == "txt"
        assert doc.content == "测试内容"
    
    def test_detect_format_recognizes_markdown(self, processor):
        """测试识别Markdown格式"""
        # Arrange
        markdown_content = "# 标题\n\n这是**粗体**文本"
        
        # Act
        format_type = processor.detect_format(markdown_content)
        
        # Assert
        assert format_type == "markdown"
    
    def test_split_by_chapter_returns_correct_segments(self, processor, sample_novel):
        """测试按章节切分返回正确片段"""
        # Arrange
        strategy = ChapterSplitStrategy()
        
        # Act
        segments = strategy.split(sample_novel)
        
        # Assert
        assert len(segments) == 2
        assert "序幕" in segments[0]
        assert "觉醒" in segments[1]
        assert "小明是一个普通的少年" in segments[0]
    
    def test_split_by_chapter_with_no_chapters_returns_single_segment(self, processor):
        """测试无章节标记时返回单个片段"""
        # Arrange
        content = "这是一段没有章节标记的文本内容。"
        strategy = ChapterSplitStrategy()
        
        # Act
        segments = strategy.split(content)
        
        # Assert
        assert len(segments) == 1
        assert segments[0] == content
    
    @pytest.mark.parametrize("content,expected_count", [
        ("# 第1章\n内容1\n# 第2章\n内容2", 2),
        ("## 第一章\n内容", 1),
        ("第1章 标题\n内容\n第2章 标题\n内容", 2),
    ])
    def test_split_handles_various_chapter_formats(self, processor, content, expected_count):
        """测试处理各种章节格式"""
        strategy = ChapterSplitStrategy()
        segments = strategy.split(content)
        assert len(segments) == expected_count
```

### 2. 实体管理器测试

```python
# tests/unit/test_entity_manager.py
import pytest
from src.managers.entity_manager import EntityManager, Entity, EntityType

class TestEntityManager:
    """实体管理器单元测试"""
    
    @pytest.fixture
    def manager(self):
        return EntityManager()
    
    @pytest.fixture
    def sample_script(self):
        return """
        【场景】古代客栈·白天
        【动作】小明推门而入，腰间别着一把崭新的宝剑。
        【对白】小明：小二，来壶茶。
        【动作】小红从楼上走下来，手持破损的长剑。
        """
    
    def test_extract_entities_from_script(self, manager, sample_script):
        """测试从剧本提取实体"""
        # Act
        entities = manager.extract_entities(sample_script)
        
        # Assert
        assert len(entities) >= 4  # 小明、小红、宝剑、长剑、客栈等
        
        characters = [e for e in entities if e.type == EntityType.CHARACTER]
        assert len(characters) >= 2
        assert any(e.name == "小明" for e in characters)
        assert any(e.name == "小红" for e in characters)
        
        props = [e for e in entities if e.type == EntityType.PROP]
        assert any(e.name == "宝剑" and "崭新" in e.state for e in props)
    
    def test_smart_bind_finds_similar_entities(self, manager):
        """测试智能绑定找到相似实体"""
        # Arrange
        extracted = Entity(name="小明", type=EntityType.CHARACTER, state="幼年")
        library = [
            EntityCard(id="1", entity_name="小明", state="青年"),
            EntityCard(id="2", entity_name="小红", state="少女"),
            EntityCard(id="3", entity_name="明哥", state="成年"),
        ]
        
        # Act
        matches = manager.smart_bind(extracted, library, threshold=0.7)
        
        # Assert
        assert len(matches) > 0
        best_match = matches[0]
        assert best_match.card.entity_name == "小明"
        assert best_match.confidence > 0.9
    
    def test_create_entity_card_with_assets(self, manager, tmp_path):
        """测试创建带素材的实体卡片"""
        # Arrange
        entity = Entity(name="小明", type=EntityType.CHARACTER, state="青年")
        image_path = tmp_path / "xiaoming.jpg"
        image_path.write_bytes(b"fake image data")
        
        # Act
        card = manager.create_entity_card(
            entity=entity,
            reference_images=[str(image_path)],
            audio_samples=[],
            video_clips=[]
        )
        
        # Assert
        assert card.entity_name == "小明"
        assert card.state == "青年"
        assert len(card.reference_images) == 1
    
    @pytest.mark.parametrize("name1,name2,expected_similarity", [
        ("小明", "小明", 1.0),
        ("小明", "小红", 0.5),
        ("张三", "张三丰", 0.7),
        ("李四", "王五", 0.0),
    ])
    def test_calculate_name_similarity(self, manager, name1, name2, expected_similarity):
        """测试名称相似度计算"""
        similarity = manager._calculate_name_similarity(name1, name2)
        assert abs(similarity - expected_similarity) < 0.2  # 允许20%误差
```

### 3. 提示词引擎测试

```python
# tests/unit/test_prompt_engine.py
import pytest
from src.engines.prompt_engine import PromptEngine, PromptTemplate

class TestPromptEngine:
    """提示词引擎单元测试"""
    
    @pytest.fixture
    def engine(self):
        return PromptEngine()
    
    @pytest.fixture
    def sample_template(self):
        return PromptTemplate(
            id="tpl_001",
            name="剧本转换模板",
            category="SCRIPT_CONVERT",
            template="将以下{content_type}转换为剧本：\n{content}",
            variables=["content_type", "content"]
        )
    
    def test_load_template_by_name(self, engine, sample_template):
        """测试按名称加载模板"""
        # Arrange
        engine._templates = {"tpl_001": sample_template}
        
        # Act
        loaded = engine.load_template("剧本转换模板")
        
        # Assert
        assert loaded.id == "tpl_001"
        assert loaded.name == "剧本转换模板"
    
    def test_render_prompt_with_variables(self, engine, sample_template):
        """测试使用变量渲染提示词"""
        # Arrange
        context = {
            "content_type": "小说",
            "content": "这是一段测试内容"
        }
        
        # Act
        rendered = engine.render_prompt(sample_template, context)
        
        # Assert
        assert "小说" in rendered
        assert "这是一段测试内容" in rendered
        assert "{content_type}" not in rendered  # 变量已替换
    
    def test_render_prompt_missing_variable_raises_error(self, engine, sample_template):
        """测试缺少变量时抛出错误"""
        # Arrange
        context = {"content_type": "小说"}  # 缺少content变量
        
        # Act & Assert
        with pytest.raises(KeyError):
            engine.render_prompt(sample_template, context)
    
    def test_recommend_style_based_on_content(self, engine):
        """测试基于内容推荐风格"""
        # Arrange
        ancient_content = "小明拿起宝剑，走进客栈。"
        modern_content = "张三打开电脑，开始编程。"
        
        # Act
        ancient_templates = engine.recommend_style(ancient_content)
        modern_templates = engine.recommend_style(modern_content)
        
        # Assert
        assert any("古风" in t.name or "武侠" in t.name for t in ancient_templates)
        assert any("现代" in t.name or "都市" in t.name for t in modern_templates)
```

### 4. 视频生成引擎测试

```python
# tests/unit/test_video_generator.py
import pytest
from unittest.mock import Mock, patch, AsyncMock
from src.engines.video_generator import VideoGenerationEngine, VideoTask

class TestVideoGenerationEngine:
    """视频生成引擎单元测试"""
    
    @pytest.fixture
    def mock_api_client(self):
        client = Mock()
        client.generate = AsyncMock(return_value="task_12345")
        client.check_status = AsyncMock(return_value="completed")
        client.download_result = AsyncMock(return_value=True)
        return client
    
    @pytest.fixture
    def engine(self, mock_api_client):
        return VideoGenerationEngine(api_client=mock_api_client)
    
    @pytest.mark.asyncio
    async def test_generate_preview_creates_short_video(self, engine, mock_api_client):
        """测试生成预览创建短视频"""
        # Arrange
        script = "【场景】测试场景"
        
        # Act
        task = await engine.generate_preview(script, duration=4)
        
        # Assert
        assert task.duration == 4
        assert task.task_id == "task_12345"
        mock_api_client.generate.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_batch_generate_processes_multiple_tasks(self, engine, mock_api_client):
        """测试批量生成处理多个任务"""
        # Arrange
        tasks = [
            VideoTask(script="剧本1", assets={}),
            VideoTask(script="剧本2", assets={}),
            VideoTask(script="剧本3", assets={}),
        ]
        
        # Act
        results = await engine.batch_generate(tasks)
        
        # Assert
        assert len(results) == 3
        assert mock_api_client.generate.call_count == 3
    
    def test_extract_keyframes_returns_images(self, engine, tmp_path):
        """测试提取关键帧返回图片"""
        # Arrange
        video_path = tmp_path / "test_video.mp4"
        video_path.write_bytes(b"fake video data")
        
        # Act
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.returncode = 0
            frames = engine.extract_keyframes(str(video_path))
        
        # Assert
        assert isinstance(frames, list)
        mock_run.assert_called_once()
```

### 5. 工作流引擎测试

```python
# tests/unit/test_workflow_engine.py
import pytest
from src.engines.workflow_engine import WorkflowEngine, WorkflowState, Project

class TestWorkflowEngine:
    """工作流引擎单元测试"""
    
    @pytest.fixture
    def sample_project(self):
        return Project(
            id="proj_001",
            name="测试项目",
            current_state=WorkflowState.INITIALIZED
        )
    
    @pytest.fixture
    def engine(self, sample_project):
        return WorkflowEngine(sample_project)
    
    def test_initial_state_is_initialized(self, engine):
        """测试初始状态为已初始化"""
        assert engine.state == WorkflowState.INITIALIZED.value
    
    def test_transition_from_initialized_to_split(self, engine):
        """测试从初始化转换到文档切分"""
        # Act
        engine.split()
        
        # Assert
        assert engine.state == WorkflowState.DOCUMENT_SPLIT.value
    
    def test_cannot_skip_required_steps(self, engine):
        """测试不能跳过必需步骤"""
        # Act & Assert
        with pytest.raises(Exception):  # 状态机会抛出异常
            engine.extract()  # 跳过split和convert直接提取实体
    
    def test_can_jump_to_state_with_sufficient_prerequisites(self, engine):
        """测试前置条件充足时可跳转状态"""
        # Arrange
        engine.project.has_scripts = True
        
        # Act
        can_jump = engine.can_jump_to(WorkflowState.ENTITIES_EXTRACTED)
        
        # Assert
        assert can_jump is True
    
    def test_checkpoint_saved_at_key_states(self, engine):
        """测试关键状态保存检查点"""
        # Arrange
        with patch.object(engine, 'checkpoint_manager') as mock_checkpoint:
            # Act
            engine.split()
            
            # Assert
            mock_checkpoint.save_checkpoint.assert_called_once()
```

## Mock和Stub策略

### 何时使用Mock

```python
# 1. 外部API调用
@patch('src.clients.openai_client.OpenAI')
def test_entity_extraction_calls_llm_api(mock_openai):
    """Mock外部LLM API"""
    mock_openai.return_value.chat.completions.create.return_value = {
        "choices": [{"message": {"content": "实体列表..."}}]
    }
    # 测试代码...

# 2. 数据库操作
@patch('src.repositories.project_repository.ProjectRepository')
def test_create_project_saves_to_database(mock_repo):
    """Mock数据库操作"""
    mock_repo.save.return_value = True
    # 测试代码...

# 3. 文件系统IO
@patch('builtins.open', create=True)
def test_save_document_writes_to_file(mock_open):
    """Mock文件写入"""
    mock_file = Mock()
    mock_open.return_value.__enter__.return_value = mock_file
    # 测试代码...
```

### Fixture复用

```python
# conftest.py - 全局fixture
import pytest
from src.models import Project, Document, EntityCard

@pytest.fixture
def sample_project():
    """标准测试项目"""
    return Project(
        id="test_proj_001",
        name="测试项目",
        current_state="initialized"
    )

@pytest.fixture
def sample_document():
    """标准测试文档"""
    return Document(
        id="doc_001",
        filename="test.txt",
        content="这是测试内容",
        format="txt"
    )

@pytest.fixture
def entity_library():
    """标准实体库"""
    return [
        EntityCard(id="1", entity_name="小明", state="青年"),
        EntityCard(id="2", entity_name="小红", state="少女"),
        EntityCard(id="3", entity_name="宝剑", state="崭新"),
    ]

@pytest.fixture
def temp_workspace(tmp_path):
    """临时工作空间"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "projects").mkdir()
    (workspace / "entity_library").mkdir()
    return workspace
```

## 测试数据管理

### 测试数据生成

```python
# tests/factories.py - 使用Factory Boy生成测试数据
import factory
from src.models import Project, Document, Entity

class ProjectFactory(factory.Factory):
    class Meta:
        model = Project
    
    id = factory.Sequence(lambda n: f"proj_{n:03d}")
    name = factory.Faker('sentence', nb_words=3)
    current_state = "initialized"

class DocumentFactory(factory.Factory):
    class Meta:
        model = Document
    
    id = factory.Sequence(lambda n: f"doc_{n:03d}")
    filename = factory.Faker('file_name', extension='txt')
    content = factory.Faker('text', max_nb_chars=200)
    format = "txt"

# 使用示例
def test_with_factory():
    project = ProjectFactory()
    doc = DocumentFactory(project_id=project.id)
    assert doc.project_id == project.id
```

## 性能测试

```python
# tests/performance/test_performance.py
import pytest
import time

class TestPerformance:
    """性能测试"""
    
    def test_document_split_performance(self, processor):
        """测试文档切分性能"""
        # Arrange
        large_content = "# 章节\n内容...\n" * 1000  # 1000章
        strategy = ChapterSplitStrategy()
        
        # Act
        start = time.time()
        segments = strategy.split(large_content)
        duration = time.time() - start
        
        # Assert
        assert duration < 10.0  # 应在10秒内完成
        assert len(segments) == 1000
    
    @pytest.mark.parametrize("size", [100, 500, 1000, 5000])
    def test_entity_matching_scales_linearly(self, manager, size):
        """测试实体匹配的扩展性"""
        # Arrange
        library = [EntityCard(id=str(i), entity_name=f"实体{i}") 
                   for i in range(size)]
        entity = Entity(name="实体500", type=EntityType.CHARACTER)
        
        # Act
        start = time.time()
        matches = manager.smart_bind(entity, library)
        duration = time.time() - start
        
        # Assert
        # 时间复杂度应接近O(n)
        assert duration < size * 0.01  # 每个实体<10ms
```

## 持续集成配置

### GitHub Actions配置

```yaml
# .github/workflows/tests.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        pip install poetry
        poetry install
    
    - name: Run tests with coverage
      run: |
        poetry run pytest --cov=src --cov-report=xml --cov-report=html
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
    
    - name: Check coverage threshold
      run: |
        poetry run pytest --cov=src --cov-fail-under=80
```

## TDD最佳实践

### 1. 测试要快
- 使用内存数据库(SQLite `:memory:`)
- Mock外部依赖
- 并行运行测试(`pytest -n auto`)

### 2. 测试要独立
- 每个测试独立的fixture
- 不依赖测试执行顺序
- 清理测试数据

### 3. 测试要可读
- 使用描述性的测试名称
- AAA模式清晰分段
- 添加必要注释

### 4. 测试要全面
- 正常路径(Happy Path)
- 边界条件(Edge Cases)
- 异常情况(Error Cases)
- 性能要求(Performance)

### 5. 重构测试代码
- 提取公共fixture
- 使用parametrize减少重复
- 遵循DRY原则

---

**文档版本**: v1.0  
**最后更新**: 2026-07-06
