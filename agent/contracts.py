"""跨层 typed 数据契约（G2：agent-native typed I/O）。

这些 dataclass 钉死工具 / 回路 / eval 的接口。字段直接来自设计文档，不是新决策：
  - RunEnd            -> ../docs/occ-fillet-debug-agent-architecture.md §24
  - GroundTruth       -> docs/root-cause-verification.md §6（四元组）
  - CausalHypothesis  -> docs/root-cause-verification.md §5（分级因果假设）
  - Stage             -> playbook/blend-failure-ontology.md §2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Stage(str, Enum):
    """blend 失效本体阶段 S0–S6（playbook/blend-failure-ontology.md §2）。"""
    S0_INPUT = "S0"      # 输入质量
    S1_SPINE = "S1"      # spine / 链抽取
    S2_SURFACE = "S2"    # blend 面构造（滚球容纳）
    S3_SSI = "S3"        # 面面求交
    S4_CORNER = "S4"     # 顶点收敛
    S5_SEW = "S5"        # 拓扑缝合
    S6_VALID = "S6"      # 输出有效性


@dataclass
class RunEnd:
    """reproduce() 的结构化结果（架构 §24）。

    注意：status 由几何有效性决定，不是裸 IsDone()。is_done 仅作诊断信号，
    禁止当成功判据（见 docs/root-cause-verification.md §2 代理奖励陷阱）。
    """
    status: str                                       # "ok" | "failed"
    exception: Optional[str] = None
    phase: Optional[str] = None
    faulty_contours: list[int] = field(default_factory=list)
    faulty_vertices: list[str] = field(default_factory=list)
    bad_shape: Optional[str] = None                   # asset 相对路径
    is_done: Optional[bool] = None                    # 仅诊断，勿当判据


@dataclass
class ValidityReport:
    """check_valid() 结果：几何有效性判据，替代 IsDone()（G17）。"""
    valid: bool
    self_intersections: list = field(default_factory=list)
    invalid_subshapes: list = field(default_factory=list)
    g1_violations: list = field(default_factory=list)
    notes: str = ""


@dataclass
class TriageReport:
    """triage_input() 结果：S0 输入预检 + 失效分类判别（G18）。

    min_dihedral_deg / min_support_curv_radius 是把 fillet-notdone 的 S2 失败分成
    geometric(近切 / r>曲率) vs algorithmic(overflow, 可 SSI 互裁) 的判别量。
    """
    sliver_faces: list = field(default_factory=list)
    short_edges: list = field(default_factory=list)
    near_tangent_pairs: list = field(default_factory=list)   # (edge_i, dihedral_deg)
    tolerance_outliers: list = field(default_factory=list)
    convexity: dict = field(default_factory=dict)            # edge_id -> "convex" | "concave"
    min_dihedral_deg: float = 180.0                          # 最小二面角；小=有近切边
    min_support_curv_radius: Optional[float] = None          # 支撑面最小曲率半径（平面=None）
    min_support_curv_face: Optional[int] = None              # 上述最小凹曲率支撑面的 OCCT 面序号（曲率型失效现场，实体级定位）


@dataclass
class ToolResult:
    """一次 agent 工具调用的 typed 信封（G2）。

    工具特定的结构化结果（RunEnd / ValidityReport / TriageReport …）放进 payload；
    这层信封统一承载"调用是否成功、产物引用、源码锚点"，由 SessionWriter 落进
    events.ndjson（进 Print viewer 供 review + 进轨迹供离线评分）。

    注意：ok 指【调用本身】成功（工具没崩），**不是几何成功**——几何成功判据是
    check_valid（G17）。reproduce 返回 status="failed" 时 ok 仍为 True（调用成功，
    几何失败的语义在 payload 里）。
    """
    tool: str                                         # 工具名，如 "reproduce" / "check_valid"
    ok: bool                                          # 调用成功（≠ 几何有效）
    summary: str = ""                                 # 一句话人读摘要
    payload: dict = field(default_factory=dict)       # 工具特定结构化结果
    artifact_id: Optional[str] = None                 # 产物引用（brep/mesh 资产路径或 id）
    source: Optional[str] = None                      # "file:line" 源码锚点
    error: Optional[str] = None                       # 结构化错误（ok=False 时填）


@dataclass
class SSIReport:
    """ssi_probe() 结果：脱离 ChFi3d 的面面求交机制证据（A7 / G23）。

    S3 失效签名：期望 ≥1 条横切 contact 曲线，实得 0 或退化（intersectSS 条数塌缩），
    且两面近切（min_dihedral_deg < tangent_eps）。clean 横切（section 实得边 ≥1 且
    夹角不近 0）则 **S3 可排除**——失败应归 S2（blend 面建不出）或 S5（缝合）。
    """
    n_curves_ss: int                  # 无界曲面 intersectSS 交线条数
    n_section_edges: int              # 有界面 section 实得 contact 边数
    min_dihedral_deg: float           # 接触/最近点两面法线夹角（近切度量）
    gap: float                        # 两面最近距离（distToShape）
    near_tangent: bool                # min_dihedral_deg < tangent_eps
    degenerate_contact: bool          # 期望 contact 但 section 0
    s3_signature: bool                # near_tangent 且 degenerate_contact → S3 机制命中
    notes: str = ""


@dataclass
class Evidence:
    """一条可被 review 的证据，锚到 artifact + source:line（架构 R6）。"""
    summary: str
    artifact_id: Optional[str] = None
    source: Optional[str] = None                      # "file:line"


@dataclass
class CausalHypothesis:
    """分级因果假设（docs/root-cause-verification.md §5）。

    agent 输出一条按证据强度排序的链；localization_depth 表示这条假设站到多深。
    根因常是因果链（症状≠根因，如 S0 近切 → 诱发 S3）：stage 是归咎的【根】(distal)，
    chain 是 distal→proximate 的传播路径（默认 [stage]，即单阶段）。
    """
    stage: Stage                                             # 归咎的根（distal）阶段
    cause: str
    chain: list[Stage] = field(default_factory=list)         # 传播链 distal→proximate；空=单阶段
    entities: list[str] = field(default_factory=list)        # 涉及的面/边/顶点
    localization_depth: str = "stage"                        # "stage" | "entity" | "mechanism"
    evidence: list[Evidence] = field(default_factory=list)
    counterfactual: Optional[str] = None                     # 靶向修法及其结果
    confidence: float = 0.0
    failure_class: Optional[str] = None                      # 失效三态：algorithmic_overflow / geometric_near_tangent / geometric_curvature（playbook failure_classes）

    def __post_init__(self):
        if not self.chain:
            self.chain = [self.stage]


@dataclass
class Conclusion:
    """investigate() 的最终产物。证据不足时 abstained=True，交人兜底。"""
    hypotheses: list[CausalHypothesis] = field(default_factory=list)   # 排序后的因果链
    abstained: bool = False
    abstain_reason: str = ""


@dataclass
class GroundTruth:
    """case 的四元组 GT（docs/root-cause-verification.md §6）。

    多由 instrumented truth run 产出；早期可用"构造已知根因的合成 case"手工标
    （见 README『已知边界』B1：早期 eval 跑在合成分布上）。

    true_chain 是因果链 distal→proximate（如 [S0, S3]：S0 近切诱发 S3 求交失败）；
    单阶段则单元素 [S3]。scorer 对链做部分得分：命中根=满分，只命中症状=部分分。
    """
    true_chain: list[Stage]                           # 因果链 distal→proximate；单阶段 [S3]；clean/弃权 case 为 []
    entities: list[str]
    expected_evidence: str
    aligned_fix: str                                  # 与该因（根）对齐的靶向修法（可执行）
    failure_class: Optional[str] = None               # 真值失效类别（playbook failure_classes 同枚举）；scorer 据此判"失效分类准确率"
    expected_abstain: bool = False                    # 正确行为是弃权（如 clean 输入无缺陷）→ scorer 判 abstention 而非定位；hallucinate 根因＝false_commit

    @property
    def root_stage(self) -> Optional[Stage]:
        """最远端（根）阶段——真正先崩的那一层；无根（弃权 case）则 None。"""
        return self.true_chain[0] if self.true_chain else None

    @property
    def symptom_stage(self) -> Optional[Stage]:
        """最近端（症状）阶段——异常被抛出的那一层；无根（弃权 case）则 None。"""
        return self.true_chain[-1] if self.true_chain else None


@dataclass
class Review:
    """人工对一条 agent 结论的裁定（A6 / G10）——review 面 O(1) 定性输入。

    verdict：
      confirm —— 认同 agent 结论（含"认同它正确弃权"）。
      correct —— agent 至少一维错；给真根 / 真失效类 / 真实体（未给的维表"该维不纠"）。
      reject  —— agent 不该下这个结论（在无缺陷输入上幻觉了根因）→ 应弃权。

    apply_review（agent/review.py）据此算 人-agent **一致率**（喂 A4）+ 产 **GT 标注**（喂 A1）。
    """
    reviewer: str
    verdict: str                                      # "confirm" | "correct" | "reject"
    target: str = ""                                  # 被 review 的 run/case 标识
    corrected_root: Optional[Stage] = None            # verdict=correct 时给真根（不给＝根不纠）
    corrected_failure_class: Optional[str] = None     # 同上，失效类别
    corrected_entities: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ReviewOutcome:
    """apply_review 结果：一致率（per-dim + overall）+ 人工裁定落成的 GT 标注。"""
    verdict: str
    agreement: dict                                   # {"root": bool, "failure_class": bool|None, "overall": bool}
    annotation: GroundTruth                           # 人工真值 → 可直接喂 scorer / 沉淀成 case GT
