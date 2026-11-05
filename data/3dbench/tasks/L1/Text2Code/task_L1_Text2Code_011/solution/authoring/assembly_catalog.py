"""Fifteen original multi-part mechanical assemblies, authored in millimetres."""
from copy import deepcopy
from math import sin,cos,pi
from mechanical_catalog import box,cyl

def assemblies():
    rows=[]
    def start(key,zh,en,description_zh,description_en):
        row=dict(family=key,title_zh=zh,title_en=en,description_zh=description_zh,description_en=description_en,parts=[],mates=[])
        rows.append(row);return row
    def part(row,name,ops,at=(0,0,0),color=(.25,.48,.65),explode=(0,0,45)):
        row['parts'].append(dict(id=name,operations=ops,at=list(at),color=list(color),explode=list(explode)))
    def plate(row,name,size,at,holes=(),color=(.25,.48,.65)):
        ops=[box(size)]+[cyl(r,size[2]+4,(x,y,0),'difference') for x,y,r in holes]
        part(row,name,ops,at,color)
    def rod(row,name,r,h,at,axis='z',color=(.65,.68,.72)):
        part(row,name,[cyl(r,h,axis=axis)],at,color)
    def ring(row,name,outer,inner,h,at,axis='z',color=(.8,.58,.2)):
        part(row,name,[cyl(outer,h,axis=axis),cyl(inner,h+4,op='difference',axis=axis)],at,color)
    def bolts(row,points,z,length=20,r=3):
        for j,(x,y) in enumerate(points):
            part(row,f'bolt_{j}',[cyl(r,length+1.5,(0,0,.75)),cyl(r*1.8,4,(0,0,length/2+3.5),vertices=6)],(x,y,z),(.55,.58,.62),(0,0,65+j*5))
            ring(row,f'washer_{j}',r*2,r+.2,1.5,(x,y,z+length/2+.75))
    def coax(row,a,b,axis='z',clearance=.2):row['mates'].append(dict(type='coaxial',a=a,b=b,axis=axis,radial_clearance_mm=clearance))

    r=start('bolted_flange','螺栓法兰联接总成','Bolted flange assembly','上下法兰、贯穿轴与四组紧固件组成可拆联接。关注孔轴同轴、垫圈贴合、轴孔间隙及爆炸顺序。','Build a detachable connection with two flanges, a through shaft and four fastener sets. Check coaxiality, washer seating, shaft clearance and explosion order.')
    holes=[(32*cos(i*pi/2),32*sin(i*pi/2),3.2) for i in range(4)]
    for name,z in [('flange_lower',6),('flange_upper',20)]:part(r,name,[cyl(45,12),cyl(10.2,16,op='difference')]+[cyl(rad,16,(x,y,0),'difference') for x,y,rad in holes],(0,0,z))
    rod(r,'shaft',10,46,(0,0,20));bolts(r,[(x,y) for x,y,_ in holes],13,26)
    coax(r,'shaft','flange_lower');coax(r,'shaft','flange_upper')

    r=start('bearing_cartridge','双支座轴承总成','Twin-support bearing assembly','轴承外圈装入两个支座，长轴穿过内孔，两端挡圈限制轴向位移。保留各自独立网格。','Fit bearing sleeves into two supports, pass a long shaft through their bores and constrain axial travel with end collars. Keep all parts as separate meshes.')
    plate(r,'base',(140,70,6),(0,0,3))
    for i,x in enumerate([-42,42]):
        part(r,f'support_{i}',[box((18,48,42)),cyl(12.2,24,(0,0,7),'difference',axis='x')],(x,0,27))
        ring(r,f'bearing_{i}',12,8.2,18,(x,0,34),'x');ring(r,f'collar_{i}',12,8.2,5,((-56 if i==0 else 56),0,34),'x');coax(r,f'bearing_{i}',f'support_{i}','x')
    rod(r,'shaft',8,130,(0,0,34),'x');coax(r,'shaft','bearing_0','x');coax(r,'shaft','bearing_1','x')
    bolts(r,[(-42,-18),(-42,18),(42,-18),(42,18)],24,48)

    r=start('knuckle_hinge','五节铰链装配','Five-knuckle hinge','两片合页交错布置五节轴套，销轴贯穿；每节之间保留轴向间隙，销轴可从顶部抽出。','Interleave five knuckles on two hinge leaves and insert a through pin. Retain axial gaps between knuckles and allow the pin to be withdrawn upward.')
    for side,x in [('left',-26),('right',26)]:
        plate(r,'leaf_'+side,(40,4,54),(x,0,27))
    for i in range(5):ring(r,f'knuckle_{i}',6,3.2,10,(0,0,5.2+i*10.8))
    rod(r,'pin',3,58,(0,0,28));rod(r,'pin_head',5,3,(0,0,58.5));ring(r,'retainer',5,3.2,2,(0,0,-2))
    for i in range(5):coax(r,'pin',f'knuckle_{i}')

    r=start('linear_carriage','双导轨滑台','Twin-rail linear carriage','滑台由双导轨、四个滑动衬套、滑板和端支架构成。滑板不能与导轨实体穿插，衬套需同轴配合。','Build a carriage with two guide rails, four sliding bushings, a carriage plate and end supports. The carriage plate must not intersect the rails, and the bushings must fit coaxially.')
    plate(r,'base',(160,90,6),(0,0,3))
    for i,y in enumerate([-25,25]):
        rod(r,f'rail_{i}',5,144,(0,y,24),'x')
        for j,x in enumerate([-18,18]):ring(r,f'bushing_{i}_{j}',9,5.2,16,(x,y,24),'x');r['parts'][-1]['operations'].append(cyl(3.2,6,(0,0,8),'difference'));coax(r,f'rail_{i}',f'bushing_{i}_{j}','x')
    for i,x in enumerate([-70,70]):part(r,f'end_support_{i}',[box((12,76,28))]+[cyl(5.2,18,(0,y,4),'difference',axis='x') for y in [-25,25]],(x,0,20))
    plate(r,'carriage',(60,74,6),(0,0,36));bolts(r,[(-18,-25),(-18,25),(18,-25),(18,25)],35,8)

    r=start('lead_screw_stage','丝杠驱动滑台','Lead-screw positioning stage','导向杆与丝杠分别承担导向和驱动，螺母座置于移动平台下方；本题不要求建模螺纹牙型。','Separate guidance and drive using guide rods and a lead screw, with a nut block under the moving platform. Thread tooth geometry is not required.')
    plate(r,'base',(170,100,6),(0,0,3))
    for i,y in enumerate([-30,30]):rod(r,f'guide_{i}',4,150,(0,y,26),'x');ring(r,f'guide_bushing_{i}',7,4.2,40,(0,y,26),'x');coax(r,f'guide_{i}',f'guide_bushing_{i}','x')
    rod(r,'lead_screw',5,160,(0,0,26),'x');part(r,'nut_block',[box((24,22,18)),cyl(5.2,28,op='difference',axis='x')],(0,0,26),(.8,.58,.2));coax(r,'lead_screw','nut_block','x')
    plate(r,'platform',(58,86,6),(0,0,38))
    for i,x in enumerate([-76,76]):part(r,f'end_{i}',[box((12,90,36))]+[cyl(rad,16,(0,y,2),'difference',axis='x') for y,rad in [(-30,4.2),(0,5.2),(30,4.2)]],(x,0,24))
    ring(r,'handwheel',18,5.2,6,(88,0,26),'x')

    r=start('machine_vise','小型机用虎钳','Compact machine vise','固定钳口与移动钳口、双导杆和驱动丝杠组成夹持机构；钳口衬片独立，行程方向一致。','Assemble fixed and moving jaws, twin guide rods and a drive screw. Keep jaw liners separate and align the direction of travel.')
    plate(r,'base',(160,90,10),(0,0,5))
    for i,x in enumerate([-60,20]):
        part(r,f'jaw_{i}',[box((18,76,50))]+[cyl(rad,24,(0,y,-8),'difference',axis='x') for y,rad in [(-25,4.2),(0,5.2),(25,4.2)]],(x,0,35))
        plate(r,f'liner_{i}',(3,76,20),(x+(10.5 if i==0 else -10.5),0,50),color=(.65,.68,.7))
    for i,y in enumerate([-25,25]):rod(r,f'guide_{i}',4,130,(0,y,27),'x')
    rod(r,'screw',5,150,(0,0,27),'x');ring(r,'handle_hub',10,5.2,12,(81,0,27),'x');r['parts'][-1]['operations'].append(cyl(3.2,26,op='difference',axis='y'));rod(r,'handle_bar',3,70,(81,0,27),'y');coax(r,'screw','jaw_1','x')

    r=start('shaft_coupling','双半联轴器','Two-hub shaft coupling','两个带凸缘的半联轴器通过螺栓相连，中心分别容纳驱动轴和从动轴，并保留端面间隙。','Connect two flanged coupling halves with bolts. Their bores hold separate driving and driven shafts, with an axial face gap.')
    for i,z in enumerate([10,32]):
        part(r,f'hub_{i}',[cyl(27,8),cyl(12,18),cyl(8.2,24,op='difference')]+[cyl(3.2,24,(20*cos(k*2*pi/3),20*sin(k*2*pi/3),0),'difference') for k in range(3)],(0,0,z))
        rod(r,f'shaft_{i}',8,24,(0,0,(-11 if i==0 else 53)));coax(r,f'shaft_{i}',f'hub_{i}')
    bolts(r,[(20*cos(k*2*pi/3),20*sin(k*2*pi/3)) for k in range(3)],21,30)
    ring(r,'spacer',14,8.4,3,(0,0,21))

    r=start('pulley_axle','滑轮支架总成','Pulley and fork assembly','轮槽、衬套、销轴、叉形支架及两端挡圈分离建模；滑轮位于叉架内部并留侧向间隙。','Model the grooved wheel, bushing, axle, fork bracket and end collars separately. Place the pulley inside the fork with side clearance.')
    plate(r,'base',(80,70,8),(0,0,4))
    for i,x in enumerate([-20,20]):part(r,f'fork_{i}',[box((8,42,64)),cyl(5.2,12,(0,0,10),'difference',axis='x')],(x,0,40))
    part(r,'pulley',[cyl(20,18,axis='x'),cyl(25,3,(-10.5,0,0),axis='x'),cyl(25,3,(10.5,0,0),axis='x'),cyl(8.2,32,op='difference',axis='x')],(0,0,50))
    ring(r,'bushing',8,5.2,24,(0,0,50),'x');rod(r,'axle',5,58,(0,0,50),'x')
    for i,x in enumerate([-28,28]):ring(r,f'collar_{i}',9,5.2,3,(x,0,50),'x')
    bolts(r,[(-30,-24),(30,-24),(-30,24),(30,24)],4,8);coax(r,'axle','bushing','x');coax(r,'pulley','bushing','x')

    r=start('rotary_table','分度转台总成','Indexing turntable assembly','底座、中心轴套、旋转盘、定位销和紧固件构成转台；分度孔均布，定位销与一个分度孔同轴。','Assemble a base, central sleeve, rotating disk, indexing pin and fasteners. Space indexing holes evenly and align the pin with one hole.')
    plate(r,'base',(100,100,8),(0,0,4),[(0,0,8.2)]);ring(r,'sleeve',14,8.2,10,(0,0,13));rod(r,'spindle',8,26,(0,0,17))
    part(r,'table',[cyl(42,8),cyl(8.2,12,op='difference')]+[cyl(3.2,12,(32*cos(k*pi/3),32*sin(k*pi/3),0),'difference') for k in range(6)],(0,0,23))
    rod(r,'index_pin',3,18,(32,0,22));ring(r,'top_retainer',13,8.2,3,(0,0,30));bolts(r,[(-40,-40),(40,-40),(-40,40),(40,40)],4,8);coax(r,'table','spindle')

    r=start('sliding_latch','滑动门闩总成','Sliding bolt latch','门闩穿过两个导向座并进入接收座，拉手、限位环及安装板单独建模。','Pass the sliding bolt through two guides into a receiver; model the handle, stop rings and mounting plate separately.')
    plate(r,'mount',(150,50,5),(0,0,2.5))
    for i,x in enumerate([-45,5,55]):part(r,f'guide_{i}',[box((14,26,25)),cyl(5.2,18,(0,0,3),'difference',axis='x')],(x,0,17.5))
    rod(r,'bolt',5,118,(5,0,20.5),'x');rod(r,'handle',3,24,(-15,0,37.5));rod(r,'grip',7,10,(-15,0,54.5))
    for i,x in enumerate([-30,25]):ring(r,f'stop_ring_{i}',8,5.2,4,(x,0,20.5),'x')
    bolts(r,[(-68,-19),(68,-19),(-68,19),(68,19)],2.5,5)
    for i in range(3):coax(r,'bolt',f'guide_{i}','x')

    r=start('sealed_enclosure','密封电子盒总成','Sealed electronics enclosure','盒体、盖板、密封圈、四个支柱和螺钉组成可维护外壳；盖板和盒体分离，密封圈不能被实体穿透。','Build a serviceable enclosure with a body, lid, gasket, four standoffs and screws. Keep the lid separate and avoid solid penetration of the gasket.')
    part(r,'body',[box((100,70,35)),box((92,62,34),(0,0,4),'difference')],(0,0,17.5))
    part(r,'gasket',[box((100,70,2)),box((92,62,6),op='difference')],(0,0,36),(.16,.17,.18))
    holes=[(x,y,2.2) for x in [-40,40] for y in [-25,25]];plate(r,'lid',(100,70,4),(0,0,39),holes)
    for i,(x,y,_) in enumerate(holes):ring(r,f'standoff_{i}',4.5,2.2,30,(x,y,21))
    bolts(r,[(x,y) for x,y,_ in holes],35,12,2)

    r=start('filter_cartridge','滤芯快拆壳体','Filter cartridge housing','筒壳、上下端盖、滤芯、密封环、贯穿拉杆和螺母组成同轴装配；所有密封和流道保持几何可见。','Assemble a housing tube, end caps, filter insert, seal rings, through rod and nut coaxially. Keep seals and flow passages geometrically explicit.')
    ring(r,'housing',30,26,70,(0,0,43));r['parts'][-1]['operations'] += [cyl(29.7,2.2,(0,0,z),'difference') for z in [-34,34]];ring(r,'filter',21,7,62,(0,0,43),color=(.85,.81,.6))
    for i,z in enumerate([4,82]):ring(r,f'cap_{i}',34,5.2,8,(0,0,z));ring(r,f'seal_{i}',29.5,26.3,2,(0,0,9 if i==0 else 77),color=(.1,.12,.13))
    rod(r,'tie_rod',5,90,(0,0,43));ring(r,'nut',9,5.2,5,(0,0,90));ring(r,'washer',11,5.2,2,(0,0,-3))
    for name in ['housing','filter','cap_0','cap_1','nut']:coax(r,'tie_rod',name)

    r=start('telescopic_tube','伸缩方管锁紧总成','Lockable telescopic square tube','内外方管以间隙配合，两个导向环、末端堵头和横向锁紧销限制运动。','Fit an inner square tube inside an outer tube with clearance; use two guide rings, an end plug and a transverse locking pin to constrain motion.')
    part(r,'outer_tube',[box((44,44,80)),box((36,36,86),op='difference'),cyl(3.2,50,(0,0,26),'difference',axis='x')],(0,0,40))
    part(r,'inner_tube',[box((32,32,90)),box((26,26,96),op='difference'),cyl(3.2,40,(0,0,-19),'difference',axis='x')],(0,0,85))
    for i,z in enumerate([8,70]):part(r,f'guide_{i}',[box((35.6,35.6,8)),box((32.4,32.4,12),op='difference')]+([cyl(3.2,42,(0,0,-4),'difference',axis='x')] if i==1 else []),(0,0,z),(.8,.58,.2))
    plate(r,'bottom_plug',(43,43,5),(0,0,-2.5));plate(r,'top_cap',(34,34,4),(0,0,132));rod(r,'locking_pin',3,58,(0,0,66),'x')
    for i,x in enumerate([-30,30]):ring(r,f'pin_retainer_{i}',6,3.2,2,(x,0,66),'x')

    r=start('camera_pan_tilt','相机双轴云台','Two-axis camera mount','底座回转轴、立柱、俯仰叉架、相机托板和双侧销轴形成嵌套装配。轴系须垂直，托板保留运动空间。','Build a nested assembly with a base pivot, pedestal, tilt fork, camera platform and side pins. The two axes must be perpendicular and leave clearance for platform movement.')
    plate(r,'base',(90,90,8),(0,0,4),[(0,0,8.2)]);ring(r,'pan_bearing',18,8.2,10,(0,0,13));rod(r,'pan_spindle',8,30,(0,0,21));plate(r,'fork_base',(64,50,6),(0,0,31),[(0,0,8.2)])
    for i,x in enumerate([-28,28]):part(r,f'fork_{i}',[box((6,50,50)),cyl(7.2,12,(0,0,10),'difference',axis='x')],(x,0,59))
    plate(r,'camera_platform',(48,64,5),(0,0,71.5));r['parts'][-1]['operations'].append(cyl(4.2,60,(0,0,-2.5),'difference',axis='x'))
    for i,x in enumerate([-24,24]):rod(r,f'tilt_pin_{i}',4,16,(x,0,69),'x');ring(r,f'tilt_bushing_{i}',7,4.2,6,((-28 if i==0 else 28),0,69),'x')
    bolts(r,[(-35,-35),(35,-35),(-35,35),(35,35)],4,8);coax(r,'pan_spindle','pan_bearing')

    r=start('roller_guide','四滚轮导向夹具','Four-roller guide fixture','四个滚轮围绕中央方形工件，轴套、轴销和支架独立；工作间隙在四侧一致。','Place four rollers around a central square workpiece, with separate bushings, pins and supports. Maintain equal working clearance on all four sides.')
    plate(r,'base',(120,120,8),(0,0,4));plate(r,'workpiece',(30,30,50),(0,0,33),color=(.8,.58,.2))
    for i,(x,y) in enumerate([(-28,0),(28,0),(0,-28),(0,28)]):
        ring(r,f'roller_{i}',12.5,4.2,28,(x,y,35));rod(r,f'pin_{i}',4,42,(x,y,31));ring(r,f'spacer_{i}',7,4.2,8,(x,y,16));coax(r,f'roller_{i}',f'pin_{i}')
    for row in rows:
        # Drill the actual fastener channels through intersecting mounting solids.
        # These features are included in public part drawings/specifications.
        for bolt in [p for p in row['parts'] if p['id'].startswith('bolt_')]:
            x,y,z=bolt['at'];rad=bolt['operations'][0]['radius']+.2
            for p in row['parts']:
                if p['id'].startswith(('bolt_','washer_')):continue
                if any(o['shape']=='box' and o.get('op')=='union' for o in p['operations']):
                    p['operations'].append(cyl(rad,400,(x-p['at'][0],y-p['at'][1],z-p['at'][2]),'difference'))
        row['level']=1;row['kind']='assembly';row['units']='millimetres';row['tolerance_mm']=.3
        # Stable explicit exploded poses separate parts, including small fasteners.
        for i,p in enumerate(row['parts']):p['explode']=[(i%4-1.5)*55,(i//4)*38,60+i*12]
        row['part_count']=len(row['parts'])
    assert len(rows)==15
    return rows
