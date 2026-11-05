重建嵌入式书架及书籍摆件、沙发和扶手椅、中央茶几、灯、地毯与面向庭院的大窗。保留书架与窗的转角关系、家具遮挡、暖色室内与日光；书籍可分组，层板、座椅、茶几与窗框要有真实深度。

输入为 input/reference.png。使用米制、Z 轴向上。主要构件须独立可编辑，有厚度、支撑和合理间隔；不得把完整参考照片放在平面或单相机投影上冒充三维场景，允许局部材质纹理。

没有原始三维模型、深度图或标定相机。以沙发坐面高 0.45 米为本题尺度约定（不是实测值），其余尺寸按比例推断，遮挡区域合理补全。

建立匹配参考的透视相机输出 main.png；复制此相机，沿自身局部 X 轴向右平移 0.30 米，保持旋转和镜头，输出 alternate.png，并保留两台相机。第二视角检查真实三维结构；看不见的真实细节不要求唯一还原。

全部输出使用同一场景、Cycles、1280 × 854 像素、AgX、曝光 0。只用给定输入建立此场景，不获取原始源模型或额外源视图。

## 提交约定

```text
output/
  solution.py
  scene.blend
  main.png
  alternate.png
  README.md
  assets/  # optional bundled dependencies
```

`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`

脚本必须从干净目录可重复运行，只读取给定 input/ 与自带 output/assets/（允许随包辅助代码及已安装库），重新写出上述场景和全部渲染。依赖以脚本相对路径解析，不依赖个人绝对路径或先前提交。README.md 写明执行与依赖。全部图像来自同一场景及规定相机，保留相机并打包材质贴图。
