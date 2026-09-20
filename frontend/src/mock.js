export const project = {name:'爱管理｜项目规划方案', period:'2026/09/13 - 2026/10/24', stories:47, must:29, should:12, could:6, phase:['可视化','一体化','AI化']};
export const members=[
 {name:'张三',role:'项目经理',systemRole:'管理员',skill:'前端',cap:80,alloc:72,color:'#2f7df6'},
 {name:'李四',role:'产品经理',systemRole:'成员',skill:'后端',cap:80,alloc:80,color:'#22b573'},
 {name:'王五',role:'前端开发',systemRole:'成员',skill:'产品',cap:80,alloc:60,color:'#7c5cff'},
 {name:'赵六',role:'测试工程师',systemRole:'观察者',skill:'测试',cap:80,alloc:64,color:'#ff9d3d'},
];
export const requirements=[
 {id:'REQ-001',title:'登录与退出',source:'I3、I7',priority:'Must',version:'v1.2',sprint:'S1',owner:'马畅',updated:'2026/09/15'},
 {id:'REQ-002',title:'项目成员与内置角色',source:'I3、I7',priority:'Must',version:'v1.0',sprint:'S1',owner:'马畅',updated:'2026/09/16'},
 {id:'REQ-016',title:'登记独立需求条目',source:'I1、I5',priority:'Must',version:'v1.0',sprint:'S1',owner:'尉旋',updated:'2026/09/17'},
 {id:'REQ-017',title:'需求列表与详情',source:'I1、I5',priority:'Must',version:'v1.1',sprint:'S1',owner:'尉旋',updated:'2026/09/18'},
 {id:'REQ-018',title:'需求编辑与版本变更',source:'I1、I5',priority:'Must',version:'v2.0',sprint:'S2',owner:'尉旋',updated:'2026/09/25'},
 {id:'REQ-019',title:'需求优先级与验收条件',source:'I1、I2',priority:'Must',version:'v1.1',sprint:'S2',owner:'尉旋',updated:'2026/09/26'},
 {id:'REQ-041',title:'AI需求拆解与估算',source:'I11、I12',priority:'Must',version:'v0.9',sprint:'S5',owner:'尉旋',updated:'2026/10/16'},
 {id:'REQ-042',title:'进度预测',source:'I11、I12',priority:'Must',version:'v0.8',sprint:'S5',owner:'师喏笛',updated:'2026/10/16'},
];
export const tasks=[
 {id:'T-031',title:'用户登录模块前端开发',req:'REQ-001',status:'进行中',owner:'张三',date:'10/18',hours:16,priority:'高'},
 {id:'T-032',title:'登录接口单元测试',req:'REQ-001',status:'进行中',owner:'王五',date:'10/19',hours:8,priority:'中'},
 {id:'T-034',title:'需求详情与版本历史开发',req:'REQ-018',status:'进行中',owner:'李四',date:'10/22',hours:20,priority:'中'},
 {id:'T-035',title:'工时与排期字段开发',req:'REQ-033',status:'进行中',owner:'张三',date:'10/23',hours:16,priority:'高'},
 {id:'T-036',title:'甘特图视图搭建',req:'REQ-034',status:'已完成',owner:'王五',date:'10/15',hours:24,priority:'高'},
 {id:'T-037',title:'个人中心页面开发',req:'REQ-012',status:'待办',owner:'李四',date:'10/20',hours:16,priority:'高'},
 {id:'T-038',title:'权限管理模块后端开发',req:'REQ-020',status:'待办',owner:'王五',date:'10/22',hours:20,priority:'中'},
 {id:'T-039',title:'系统日志功能开发',req:'REQ-022',status:'待办',owner:'赵六',date:'10/24',hours:12,priority:'低'},
 {id:'T-028',title:'项目创建与基本信息',req:'REQ-005',status:'待验收',owner:'王五',date:'10/16',hours:8,priority:'中'},
 {id:'T-029',title:'成员邀请与加入流程',req:'REQ-006',status:'待验收',owner:'李四',date:'10/17',hours:8,priority:'中'},
 {id:'T-026',title:'需求列表页开发',req:'REQ-008',status:'已完成',owner:'李四',date:'10/12',hours:12,priority:'低'},
 {id:'T-027',title:'需求创建与编辑',req:'REQ-009',status:'已完成',owner:'张三',date:'10/13',hours:10,priority:'中'},
];
export const gantt=[
 {group:'项目启动',title:'需求调研',owner:'李四',start:'09/13',end:'09/15',hours:16,color:'blue',x:0,w:12},
 {group:'项目启动',title:'需求分析',owner:'王五',start:'09/14',end:'09/17',hours:24,color:'blue',x:7,w:18},
 {group:'项目启动',title:'项目启动会',owner:'张三',start:'09/18',end:'09/19',hours:8,color:'blue',x:20,w:9},
 {group:'可视化阶段',title:'原型设计',owner:'张三',start:'09/20',end:'09/23',hours:32,color:'green',x:29,w:18},
 {group:'可视化阶段',title:'UI设计',owner:'赵六',start:'09/21',end:'09/25',hours:40,color:'green',x:33,w:24},
 {group:'一体化阶段',title:'前端开发',owner:'李四',start:'10/04',end:'10/07',hours:80,color:'orange',x:52,w:20},
 {group:'一体化阶段',title:'后端开发',owner:'张三',start:'10/04',end:'10/08',hours:80,color:'orange',x:52,w:26},
 {group:'AI化阶段',title:'AI需求拆解',owner:'张三',start:'10/14',end:'10/16',hours:40,color:'purple',x:76,w:11},
 {group:'AI化阶段',title:'进度预测',owner:'赵六',start:'10/15',end:'10/17',hours:40,color:'purple',x:80,w:11},
 {group:'AI化阶段',title:'智能排期',owner:'王五',start:'10/16',end:'10/18',hours:40,color:'purple',x:84,w:10},
 {group:'项目收尾',title:'验收发布',owner:'张三',start:'10/21',end:'10/24',hours:40,color:'blue',x:92,w:8},
];
