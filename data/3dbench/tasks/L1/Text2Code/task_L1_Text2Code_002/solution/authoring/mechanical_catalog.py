"""Original CAD-like CSG families. All dimensions here are millimetres.

This authoring catalog is NOT supplied to image reconstruction agents.
Each output is a single connected manufactured-style part, not an assembly.
"""
from math import cos, sin, pi

def box(size, at=(0,0,0), op='union', label=''):
    return dict(shape='box',size=list(size),at=list(at),op=op,label=label)

def cyl(radius, height, at=(0,0,0), op='union', vertices=96, axis='z', label=''):
    return dict(shape='cylinder',radius=radius,height=height,at=list(at),op=op,
                vertices=vertices,axis=axis,label=label)

def cone(bottom,top,height,at=(0,0,0),op='union',label=''):
    return dict(shape='cone',radius=bottom,radius_top=top,height=height,at=list(at),op=op,label=label)

def catalog():
    items=[]
    def put(key,title,description,ops,features,difficulty,edit_index=None,edit_field=None):
        items.append(dict(family=key,title=title,description=description,operations=ops,
            features=features,design_difficulty=difficulty,edit_index=edit_index,edit_field=edit_field))
    put('washer','偏置双孔安装垫片','外径60、厚6；中心通孔直径20；另一个直径6的通孔位于(21,0)。',
        [cyl(30,6,(0,0,3)),cyl(10,10,(0,0,3),'difference',label='central_bore'),cyl(3,10,(21,0,3),'difference',label='index_hole')],3,'easy',1,'radius')
    put('flange','四孔轴承法兰','底盘直径80厚8；中心凸台直径40高12；贯穿中心孔直径20；四个直径8的螺孔位于半径30的圆上。',
        [cyl(40,8,(0,0,4)),cyl(20,12.2,(0,0,13.9)),cyl(10,24,(0,0,10),'difference',label='bore')]+[cyl(4,12,(30*cos(i*pi/2),30*sin(i*pi/2),4),'difference',label=f'bolt_{i}') for i in range(4)],8,'hard',2,'radius')
    put('bracket','双向孔直角支架','底板60×40×6；后缘立板60×6×40，与底板相连；底板两个直径8孔在(±18,-5)，立板沿Y方向直径10孔中心(0,17,25)。',
        [box((60,40,6),(0,0,3)),box((60,6,40),(0,17,20)),cyl(4,10,(-18,-5,3),'difference'),cyl(4,10,(18,-5,3),'difference'),cyl(5,12,(0,17,25),'difference',axis='y')],6,'hard',4,'radius')
    put('socket','盲孔定位座','外形50×40×24；中央直径24盲孔深16，保留8厚底；两个直径5安装通孔在(±19,0)。',
        [box((50,40,24),(0,0,12)),cyl(12,18,(0,0,17),'difference'),cyl(2.5,28,(-19,0,12),'difference'),cyl(2.5,28,(19,0,12),'difference')],5,'medium',1,'radius')
    put('pulley','双边轮缘皮带轮','轴线为Z；轮芯直径44、高24；上下轮缘直径60、厚4；中心直径12通孔。整体高度32。',
        [cyl(22,24.2,(0,0,16)),cyl(30,4,(0,0,2)),cyl(30,4,(0,0,30)),cyl(6,36,(0,0,16),'difference')],5,'medium',3,'radius')
    put('tray','矩形收纳托盘','外尺寸80×60×20；壁厚4、底厚3，顶部开放。',
        [box((80,60,20),(0,0,10)),box((72,52,20),(0,0,13),'difference')],3,'easy',1,'size')
    put('cup','带把手杯','杯身外径50高55，壁厚3底厚4；环形把手位于右侧XZ平面，外径30内径20，沿Y厚8，与杯壁接合。',
        [cyl(25,55,(0,0,27.5)),cyl(15,8,(29,0,30),axis='y'),cyl(10,12,(29,0,30),'difference',axis='y'),cyl(22,55,(0,0,31.5),'difference')],6,'hard',3,'radius')
    put('pipe_reducer','同心变径管','高50，外部下端直径50、上端直径30；内部下端直径42、上端直径22，贯通两端。',
        [cone(25,15,50,(0,0,25)),cone(21.4,10.6,54,(0,0,25),'difference')],4,'medium',1,'radius')
    put('nut','六角螺母毛坯','正六边形外轮廓外接圆直径40，高16；中心直径16通孔，不要求螺纹。',
        [cyl(20,16,(0,0,8),vertices=6),cyl(8,20,(0,0,8),'difference')],3,'easy',1,'radius')
    put('knob','六槽控制旋钮','圆盘直径50高16，顶面中心凸台直径14高5；周边六个半径4竖直凹槽，其轴线均匀位于半径25圆上；底部直径10盲孔深10。',
        [cyl(25,16,(0,0,8)),cyl(7,5.2,(0,0,18.4))]+[cyl(4,20,(25*cos(i*pi/3),25*sin(i*pi/3),8),'difference') for i in range(6)]+[cyl(5,12,(0,0,4),'difference')],10,'hard',8,'radius')
    put('spacer','阶梯绝缘套','底缘直径36厚5，上段直径24高25；中心直径12通孔，总高30。',
        [cyl(18,5,(0,0,2.5)),cyl(12,25.2,(0,0,17.4)),cyl(6,34,(0,0,15),'difference')],4,'easy')
    put('shaft','三级传动轴','三个同轴圆柱从下到上：直径30高15、直径22高30、直径14高20；顶部轴段上开宽5、径向深3、长14键槽。',
        [cyl(15,15,(0,0,7.5)),cyl(11,30.2,(0,0,29.9)),cyl(7,20.2,(0,0,54.9)),box((5,6,14),(0,7,55),'difference')],6,'medium')
    put('comb','八齿间距梳','背脊64×8×8；8个宽4、长28、高8的齿沿X等距8排列，与背脊接合，齿朝负Y。',
        [box((64,8,8),(0,0,4))]+[box((4,28.2,8),(-28+i*8,-17.9,4)) for i in range(8)],10,'medium')
    put('heatsink','七片散热器','底板60×40×5；7片厚3、高20、长40散热鳍沿X轴以8为间距排列。',
        [box((60,40,5),(0,0,2.5))]+[box((3,40,20.2),(-24+i*8,0,14.9)) for i in range(7)],9,'medium')
    put('perforated','交错孔筛板','80×50×5板，3行5列直径6通孔；X间距14、Y间距14，中心行在X方向偏移4。',
        [box((80,50,5),(0,0,2.5))]+[cyl(3,9,(-28+i*14+(4 if j==1 else 0),-14+j*14,2.5),'difference') for j in range(3) for i in range(5)],16,'hard')
    put('enclosure','带安装耳电子盒','主体60×40×25、壁厚3底厚3；两侧各一个12×20×5安装耳；耳上直径5通孔在(±35,0)。',
        [box((60,40,25),(0,0,12.5)),box((12,20,5),(-35,0,2.5)),box((12,20,5),(35,0,2.5)),box((54,34,25),(0,0,15.5),'difference'),cyl(2.5,9,(-35,0,2.5),'difference'),cyl(2.5,9,(35,0,2.5),'difference')],8,'hard')
    put('funnel','贯通漏斗','上段高40，底半径8顶半径30；下方接外径16、高20的直管。漏斗壁厚按径向2设计，管内径12。总高60。',
        [cone(8,30,40.2,(0,0,39.9)),cyl(8,20.2,(0,0,10)),cone(5.8,28.2,40.8,(0,0,40),'difference'),cyl(6,24,(0,0,10),'difference')],6,'hard')
    put('bottle','空心实验瓶','主体外径40高50；锥形肩部高12从外径40过渡到16；瓶颈外径16高15；底厚3；主体内径34，瓶口内径10，内部连通。',
        [cyl(20,50,(0,0,25)),cone(20,8,12.2,(0,0,55.9)),cyl(8,15.2,(0,0,69.4)),cyl(17,47.4,(0,0,26.7),'difference'),cone(17,5,12.4,(0,0,55.9),'difference'),cyl(5,18,(0,0,69),'difference')],8,'hard')
    put('spool','线轴','总高50；上下圆盘直径70厚6，中柱直径28；中心直径10通孔。',
        [cyl(35,6,(0,0,3)),cyl(14,38.4,(0,0,25)),cyl(35,6,(0,0,47)),cyl(5,54,(0,0,25),'difference')],5,'medium')
    put('bridge_mount','跨线桥形座','底部两脚各12×30×20，中心X=±24；顶板60×30×6，底面Z=18；中央竖向直径8通孔。',
        [box((12,30,20),(-24,0,10)),box((60,30,6),(0,0,21)),box((12,30,20),(24,0,10)),cyl(4,10,(0,0,21),'difference')],6,'medium')
    put('cross_connector','十字连接片','水平长臂80×16×6，垂直长臂16×64×6；端部四个直径6通孔在(±30,0)、(0,±22)。',
        [box((80,16,6),(0,0,3)),box((16,64,6),(0,0,3))]+[cyl(3,10,(x,y,3),'difference') for x,y in [(-30,0),(30,0),(0,-22),(0,22)]],7,'medium')
    put('counterbore','沉孔紧固板','60×40×10；两个直径6通孔在(±18,0)，各孔上方同轴直径12沉孔深4。',
        [box((60,40,10),(0,0,5))]+[op for x in [-18,18] for op in [cyl(3,14,(x,0,5),'difference'),cyl(6,6,(x,0,9),'difference')]],6,'medium')
    put('slot_plate','双长圆槽底座','80×45×8；两条沿X的长圆通槽，圆端中心X=±20、半径4；槽中心Y=±11。',
        [box((80,45,8),(0,0,4))]+[op for y in [-11,11] for op in [box((40,8,12),(0,y,4),'difference'),cyl(4,12,(-20,y,4),'difference'),cyl(4,12,(20,y,4),'difference')]],7,'hard')
    put('pencil_holder','九孔笔架','60×60×35实体，3×3阵列直径10盲孔，XY间距18，孔深28，底厚7。',
        [box((60,60,35),(0,0,17.5))]+[cyl(5,30,(x,y,22),'difference') for x in [-18,0,18] for y in [-18,0,18]],10,'medium')
    put('t_joint','T形空心接头','竖管外径24、内径16、高50；横向支管沿X连接中心(15,0,25)，长度30、外径20、内径12；三端连通。',
        [cyl(12,50,(0,0,25)),cyl(10,30,(15,0,25),axis='x'),cyl(8,54,(0,0,25),'difference'),cyl(6,34,(15,0,25),'difference',axis='x')],6,'hard')
    put('stepped_cup','双台阶零件盘','底部外径60高8，上部外径48高20；中央直径36盲腔深22，留6厚底。',
        [cyl(30,8,(0,0,4)),cyl(24,20.2,(0,0,17.9)),cyl(18,24,(0,0,18),'difference')],4,'easy')
    put('grid_divider','四格分类盒','外尺寸64×64×20，外壁和底厚3；中央十字隔板厚4，与底部连成整体。',
        [box((64,64,20),(0,0,10)),box((58,58,20),(0,0,13),'difference'),box((4,58.2,17.2),(0,0,11.4)),box((58.2,4,17.2),(0,0,11.4))],6,'medium')
    put('c_clamp','C形夹持框','外框50×30×60，开口朝正X；内部去除44×34×42盒，其中心(6,0,30)；上横梁中心(12,0,55)有直径8竖孔。',
        [box((50,30,60),(0,0,30)),box((44,34,42),(6,0,30),'difference'),cyl(4,14,(12,0,55),'difference')],5,'medium')
    put('rack','五级阶梯展示座','底面60×50；沿正Y排列5级，每级进深10、升高6，从负Y端高6到正Y端高30。',
        [box((60,10.1,6*(i+1)),(0,-20+10*i,3*(i+1))) for i in range(5)],6,'easy')
    put('radial_cap','八辐条镂空端盖','外环外径70内径58、厚6；中心轮毂直径18；8条径向辐条宽5，连接轮毂与外环；中心直径8通孔。',
        [cyl(35,6,(0,0,3)),cyl(29,10,(0,0,3),'difference'),cyl(9,6,(0,0,3))]+[dict(box((62,5,6),(0,0,3)),rotation_z=i*45) for i in range(4)]+[cyl(4,10,(0,0,3),'difference')],12,'hard')
    assert len(items)==30
    return items
