"""Task-specific visual component scoring for four reference reconstruction tasks.

Each task maps frozen visual criteria to image, semantic and detail components.
The model identity and desired ranking are never inputs to the scoring rule.
"""
from copy import deepcopy
import math

from src.evaluator.legacy_detail import ratio

VERSION = 'legacy-detail-20261019-v2'
BASELINE = 'legacy-detail-20261018-v1'
REVISION = 'direct-components-linear-r2'
# Each new visual observation replaces only the named quality component. The
# localization measurement remains the frozen v1 observation. This keeps one
# structural defect from multiplying every component a second time.
COMPONENT_RULES = {
    'L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_001': {
        'main_image': [('shoe_profile', .50), ('shoe_upper', .50)],
        'vlm': [('shoe_laces', 1.)], 'detail': [('shoe_sole', 1.)]},
    'L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_009': {
        'main_image': [('horse_profile', 2/3), ('horse_neck', 1/3)],
        'vlm': [('horse_anatomy', 1.)], 'detail': [('horse_mane', 1.)]},
    'L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_010': {
        'main_image': [('david_face', .70), ('david_bust', .30)],
        'vlm': [('david_surface', 1.)], 'detail': [('david_hair', 1.)]},
    'L2/Reference2Scene/task_L2_Reference2Scene-005': {
        'main_image': [('city_layout', .50), ('city_buildings', .50)],
        'vlm': [('city_facades', 1.)], 'detail': [('city_roofs', 1.)]},
}
TASK_RULES = {
    'L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_001': [
        ('shoe_profile', .30, '鞋的具体整体形态', ['鞋头收分与高度', '后跟到前掌的曲线', '鞋面相对鞋底的体积', '参考视角下前后左右比例']),
        ('shoe_upper', .30, '连续鞋面和开口', ['弯曲连续鞋面', '有厚度的鞋领开口', '后跟软垫与鞋舌', '侧片主要轮廓及其连接']),
        ('shoe_laces', .20, '鞋带与鞋面连接关系', ['穿孔处连接', '交叉鞋带走向', '鞋带下真实间隙', '鞋舌与鞋带的遮挡关系']),
        ('shoe_sole', .20, '分层鞋底形态', ['中底与外底层次', '沿长度变化的厚度', '前掌及后跟曲面', '鞋底与鞋面贴合关系']),
    ],
    'L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_009': [
        ('horse_profile', .30, '参考马头的具体比例', ['长额头至口鼻的连续侧线', '头部朝向及长宽比例', '下颌的具体轮廓', '头与颈部的相对比例']),
        ('horse_anatomy', .30, '头部解剖曲面', ['竖耳及耳内凹陷', '嵌入头部的眼眶和眼睛', '口鼻的体积与鼻孔', '额头面颊下颌的连续过渡']),
        ('horse_mane', .25, '后掠鬃毛的雕塑体积', ['主要毛束的后掠方向', '大小不一的层叠曲面体积', '毛束之间的沟槽', '鬃毛与颈部的连续连接']),
        ('horse_neck', .15, '颈胸及底座关系', ['颈部至胸部的连续弧面', '颈胸切面形态', '矩形底座的比例', '颈胸落在底座上的位置与连接']),
    ],
    'L1/Image2Code-SingleView/task_L1_Image2Code-SingleView_010': [
        ('david_face', .35, '大卫面部的特定比例', ['额头眉弓与眼窝的空间关系', '鼻梁鼻翼及鼻唇比例', '嘴唇下巴及颌线形态', '头部倾斜和面部整体比例']),
        ('david_surface', .25, '连续面部及耳廓曲面', ['眉弓眼窝的连续凹凸', '颧骨面颊鼻部的过渡', '嘴唇下巴的连续雕塑曲面', '可见耳廓及其与头部连接']),
        ('david_hair', .25, '成簇卷发的具体结构', ['参考可见发簇的分布', '层叠卷曲体积', '发簇之间沟槽', '发际线与头部的连接']),
        ('david_bust', .15, '颈肩胸像的形态', ['倾斜头部与颈部的关系', '颈部连续曲率', '肩部切面的形态', '头颈肩相对尺寸']),
    ],
    'L2/Reference2Scene/task_L2_Reference2Scene-005': [
        ('city_layout', .30, '参考可见路网与街区组织', ['主要交叉道路的方向与宽窄关系', '街区相对占地与形状', '高低建筑在街区中的具体分布', '前中后景遮挡关系']),
        ('city_buildings', .30, '主要建筑的特定体量', ['前景主要建筑的轮廓和高度关系', '中心主要建筑的轮廓和高度关系', '后景主要建筑的轮廓和高度关系', '参考可见的退台及组合体块']),
        ('city_facades', .20, '建筑立面结构', ['不同建筑的窗格尺度与组织', '层间线和竖向分隔', '立面凹凸及建筑间差异', '窗格与建筑体量的比例']),
        ('city_roofs', .20, '屋顶结构和道路留空', ['主要屋顶轮廓及退台', '可见屋顶设施的体积与布局', '建筑之间真实街道留空', '屋顶高度层次及其遮挡']),
    ],
}


def linear_observations(task_id, criteria):
    """Reuse c/e observations, never the previous squared score column."""
    expected = {r[0] for r in TASK_RULES[task_id]}
    if len(criteria) != len(expected) or {c['check_id'] for c in criteria} != expected:
        raise ValueError('Exact task-specific criterion population required')
    values = {}
    for criterion in criteria:
        coverage, deviation = ratio(criterion['coverage']), ratio(criterion['deviation'])
        if coverage == 0 and deviation != 0:
            raise ValueError('Missing content must not also incur deviation')
        values[criterion['check_id']] = coverage * (1-deviation)
    return values


def component_scores(task_id, criterion_scores):
    """Aggregate each new observation into its one replacement component."""
    if task_id not in COMPONENT_RULES:
        raise ValueError('No scoped component mapping for task')
    expected = {key for rules in COMPONENT_RULES[task_id].values() for key, _ in rules}
    population = [key for rules in COMPONENT_RULES[task_id].values() for key, _ in rules]
    if len(population) != len(expected):
        raise ValueError('A criterion must belong to exactly one component')
    if set(criterion_scores) != expected:
        raise ValueError('Exact task-specific criterion population required')
    values = {}
    for component, rules in COMPONENT_RULES[task_id].items():
        if not math.isclose(math.fsum(weight for _, weight in rules), 1, abs_tol=1e-12):
            raise ValueError('Replacement component weights must sum to one')
        values[component] = math.fsum(weight * ratio(criterion_scores[key]) for key, weight in rules)
    return values


def revise(row, criterion_scores):
    """Replace image/VLM/detail directly; retain v1 localization and weights."""
    if row['task_id'] not in TASK_RULES:
        if criterion_scores is not None:
            raise ValueError('Cannot revise a task outside the four-task scope')
        return deepcopy(row)
    replacement = None if criterion_scores is None else component_scores(row['task_id'], criterion_scores)
    output = deepcopy(row)
    components = deepcopy(row['components'])
    for key in COMPONENT_RULES[row['task_id']]:
        components[key] = None if replacement is None else replacement[key]
    weights = row['component_weights']
    if not math.isclose(sum(weights.values()), 1, abs_tol=1e-12):
        raise ValueError('Baseline weights must sum to one')
    if row['effective_validity']:
        replay = math.fsum(ratio(row['components'][k]) * w for k, w in weights.items())
        if not math.isclose(replay, row['S_core'], abs_tol=1e-10):
            raise ValueError('Baseline component arithmetic changed')
        total = None if replacement is None else math.fsum(components[k] * w for k, w in weights.items())
    else:
        total = 0.
    output.update(release_id=VERSION, profile=VERSION+'/'+row['category'],
                  baseline_score_100=row['score_100'], baseline_components=deepcopy(row['components']),
                  criterion_scores=deepcopy(criterion_scores), scoring_revision=REVISION,
                  replacement_components=deepcopy(replacement),
                  components=components, S_core=total, score_100=None if total is None else 100*total,
                  delta_points=None if total is None else 100*total-row['score_100'],
                  scoring_change='direct_component_replacement_v2',
                  preserved_components=['localization'])
    return output
