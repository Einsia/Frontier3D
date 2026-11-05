铁匠铺侧边雨棚下的炉台、风箱和铁砧组件缺失。按 input/reference.png 补回炉台边沿与凹入工作区、旁侧风箱、带尖角和收腰的铁砧、下方支座及固定细节，以及图中的两件小型热铁。保留设备之间的操作空间。匹配参考中的中性灰模表现及少量暖色炉火点缀，不另加一种贴图风格。建筑、雨棚、悬挂工具、桶、台阶及其余保留几何不变。

从 input/initial.blend 开始，使用唯一参考图。保留上文允许修改范围以外的全部场景数据，包括相机和渲染、色彩设置。给定主相机渲染 main.png；复制主相机，沿局部 X 正方向平移 0.30 m，镜头及旋转不变，渲染 alternate.png。两个相机保存在同一编辑后的场景中，全部依赖打包。隐藏细节可合理补全。

仅用提供的输入确定此场景，不联网取回原完整工程或额外视图，不能将完整参考图投到平面上代替三维结构。

## 固定交付结构
请把所有交付物放在任务工作区的 `output/` 下，评测器只读取以下固定路径：

```text
output/
  solution.py       # 可重复运行的 Blender 建模或修改入口
  scene.blend       # 可编辑的原生场景
  main.png          # 必需的主视角
  alternate.png    # 必需的第二视角
  README.md         # 简短依赖和运行说明
  assets/           # 可选的本地贴图或运行所需文件
```

在干净副本中用后台 Blender 运行：`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`。程序必须相对于自身定位辅助文件，仅从提供的 `input/` 和自己的 `output/assets/` 读取任务数据（可使用随附辅助代码和已安装库），并在 `output/` 刷新场景及两张图片；不得依赖之前的提交、个人绝对路径或工作区外文件。两张图片必须来自同一个保存的场景并遵守上文相机/渲染要求；文件名必须完全一致，额外文件放入 `output/renders/` 或 `output/logs/`。


## 程序化材质约束
使用提供的 initial.blend 和参考图；只允许纯色或程序化着色，不得使用图像纹理。遵守题目规定的编辑范围和相机、渲染要求。
