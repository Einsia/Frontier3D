阁楼右侧的望远镜及三脚支架已被移除。按 input/reference.png 补回长倾斜镜筒、较大的前端口沿、目镜端、安装关节和细三脚支撑，利用保留家具及墙面判断大小与位置。镜筒连接安装座，安装座连接三脚架，支脚落地。匹配深色表面和细长轮廓。不改书桌、显示器、凳子、海报、地球仪、墙面、照明及其他保留物体。

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
