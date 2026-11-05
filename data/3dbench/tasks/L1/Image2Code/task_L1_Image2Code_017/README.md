# 波音 787-9 客机

重建澳航波音 787-9 的细长机身、后掠机翼、双发动机舱、尾翼及可见起落架，保留翼面曲率、发动机开口、比例和白红涂装。细小字样与面板线可简化，不要求飞行仿真。

- 类别：Image2Code；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；四张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[mudkipz321](https://sketchfab.com/3d-models/boeing-787-9-qantas-centenary-4b061566dc5a4495bff5e8c7e911ec4e)，CC-BY-4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras. Baked the evaluated source pose at frame 1; source animation omitted from the static task.
