// 桌宠管家 —— 全量配置目录（由原型 HTML 生成，勿手工改数据段）。
//
// 这一份是唯一真值：host.mjs 用它校验/分流写盘，client.js 经 /api/state 拿到
// 同一份 JSON 渲染配置目录。数据段与 .workbuddy/scratch/
// xiaoxiao-pet-manager-prototype-full.html 保持同步（脚本：gen-catalog.cjs）。
//
// 桌宠配置真值分两处：config.json（全局）与 config-slot-0.json（每宠键，见
// pet/pet_profiles.py 的 PER_PET_SETTING_KEYS）。目录里另有一批带点号的嵌套键
// 与复合控件（菜单编排 / 功能卡 / 快捷启动列表），写盘规则在 core.mjs。

/* ---------- 紧凑 DSL：一行一个配置项 ---------- */
function O(s){return s.split("|").map(function(p){var i=p.indexOf(":"),l=p.slice(0,i),v=p.slice(i+1);if(v!==""&&!isNaN(Number(v)))v=Number(v);return [v,l];});}
function t(k,l,d,n){return {k:k,l:l,t:"toggle",d:d===undefined?false:d,n:n};}
function s(k,l,d,o,n){return {k:k,l:l,t:"select",d:d,o:O(o),n:n};}
function r(k,l,d,a,b,st,u,n){return {k:k,l:l,t:"range",d:d,min:a,max:b,step:st,u:u,n:n};}
function num(k,l,d,a,b,st,u,n){return {k:k,l:l,t:"number",d:d,min:a,max:b,step:st,u:u,n:n};}
function x(k,l,d,type,n){return {k:k,l:l,t:type||"text",d:d===undefined?"":d,n:n};}
function act(l,n){return {l:l,t:"action",n:n||"动作"};}
function note(txt){return {l:txt,t:"note"};}
function wide(f){f.wide=true;return f;}
function mp(k,l,d){return {k:k,l:l,t:"models",d:d};}
// 小工位「设置 → 模型」那整页：下拉选择 + 添加/删除 + 单条表单，一个复合控件管到底。
function pr(k,l){return {k:k,l:l,t:"providers"};}

/* ---------- 真实默认菜单模板节点 ---------- */
var MENU_NODES=[
 {type:"action",id:"ojingjing",label:"厉害了我的鲸",visible:false,section:"profile"},
 {type:"separator",id:"default.separator-profile",label:"分隔线",visible:false},
 {type:"action",id:"quick_chat",label:"和她聊天",visible:true,section:"interaction"},
 {type:"action",id:"work_station",label:"打开小工位",visible:true,section:"interaction"},
 {type:"action",id:"work_for_laji",label:"打工",visible:true,section:"interaction"},
 {type:"action",id:"chat",label:"AI 对话",visible:false,section:"interaction"},
 {type:"action",id:"look_screen",label:"看看屏幕",visible:false,section:"interaction"},
 {type:"action",id:"screen_capture",label:"截图提问",visible:false,section:"interaction"},
 {type:"separator",id:"default.separator-interaction",label:"分隔线",visible:false},
 {type:"action",id:"animations_hub",label:"播放动画",visible:false,section:"playback"},
 {type:"action",id:"character",label:"切换角色",visible:false,section:"playback"},
 {type:"action",id:"playback_speed",label:"播放速率",visible:false,section:"playback"},
 {type:"action",id:"size",label:"大小",visible:false,section:"playback"},
 {type:"submenu",id:"music",label:"音乐",visible:false,section:"playback",children:[
   {type:"action",id:"music_pause",label:"暂停 / 播放",visible:true},
   {type:"action",id:"music_next",label:"切歌",visible:true},
   {type:"action",id:"music_prev",label:"上一首",visible:true},
   {type:"action",id:"music_quit",label:"退出音乐模式",visible:true},
   {type:"action",id:"music_lyric_align",label:"歌词对齐",visible:true},
   {type:"separator",id:"music.separator-launch",label:"分隔线",visible:true},
   {type:"action",id:"music_open_netease",label:"打开网易云并播放",visible:true},
   {type:"action",id:"music_open_qqmusic",label:"打开 QQ 音乐",visible:true},
   {type:"action",id:"music_open_kugou",label:"打开酷狗",visible:true},
   {type:"action",id:"music_open_soda",label:"打开汽水",visible:true}]},
 {type:"separator",id:"default.separator-playback",label:"分隔线",visible:false},
 {type:"submenu",id:"pet_controls",label:"桌宠控制",visible:false,section:"pet",children:[
   {type:"action",id:"drag_physics",label:"拖动物理",visible:true},
   {type:"action",id:"no_move",label:"不移动",visible:true},
   {type:"action",id:"on_top",label:"窗口置顶",visible:true},
   {type:"action",id:"autostart",label:"开机自启",visible:true},
   {type:"action",id:"return_corner",label:"回到左上角",visible:true},
   {type:"action",id:"hide_pet",label:"隐藏桌宠",visible:true},
   {type:"action",id:"spawn_pet",label:"生小肥鱼",visible:true},
   {type:"action",id:"clear_spawned_pets",label:"退出子肥鱼",visible:true},
   {type:"action",id:"agent_cost",label:"显示本轮消费",visible:true},
   {type:"action",id:"golden_spin",label:"黄金回旋",visible:true},
   {type:"action",id:"edge_probe",label:"边缘探头",visible:true}]},
 {type:"action",id:"quick_launch",label:"快捷启动",visible:false,section:"pet"},
 {type:"separator",id:"default.separator-pet",label:"分隔线",visible:false},
 {type:"submenu",id:"tools_help",label:"工具与帮助",visible:false,section:"tools",children:[
   {type:"action",id:"balance",label:"DeepSeek 余额",visible:true},
   {type:"action",id:"harness",label:"启动 DeepSeek Harness",visible:true},
   {type:"action",id:"deepseek_web",label:"打开网页版 DeepSeek",visible:true},
   {type:"action",id:"check_update",label:"检查更新",visible:true},
   {type:"action",id:"network_info",label:"网络信息",visible:true},
   {type:"action",id:"github_project",label:"GitHub 项目页",visible:true},
   {type:"action",id:"quark_download",label:"夸克网盘下载",visible:true}]},
 {type:"action",id:"agent_link",label:"Agent 联动",visible:false,section:"tools"},
 {type:"action",id:"proactive_screen",label:"主动识屏",visible:false,section:"tools"},
 {type:"action",id:"todo_panel",label:"待办提醒",visible:false,section:"tools"},
 {type:"action",id:"quiet_mode",label:"免打扰",visible:false,section:"tools"},
 {type:"action",id:"memory_trim",label:"回收内存",visible:false,section:"tools"},
 {type:"action",id:"weather",label:"查看天气",visible:false,section:"tools"},
 {type:"action",id:"weather_cities",label:"天气城市",visible:false,section:"tools"},
 {type:"action",id:"voice_chime_now",label:"立即报时",visible:false,section:"tools"},
 {type:"action",id:"voice_chime_toggle",label:"启用 / 关闭语音报时",visible:false,section:"tools"},
 {type:"action",id:"festival_now",label:"今日节日",visible:false,section:"tools"},
 {type:"action",id:"festival_toggle",label:"启用 / 关闭节日提醒",visible:false,section:"tools"},
 {type:"action",id:"divination_draw",label:"抽支签",visible:false,section:"tools"},
 {type:"separator",id:"default.separator-tools",label:"分隔线",visible:false},
 {type:"action",id:"modern_settings",label:"桌宠设置",visible:true,alias:"小口袋",section:"system"},
 {type:"action",id:"quit",label:"退出",visible:true,section:"system"}
];

var FEATURES=[
 {cat:"生活",items:[["weather","天气","定时播报天气"],["divination","抽签","每日一签"],["todo","待办提醒","任务与提醒"],["festival","节日提醒","节日与节气"]]},
 {cat:"语音",items:[["voice","语音","报时 / 朗读"],["music","音乐","跟着音乐唱歌"]]},
 {cat:"智能",items:[["chat","AI 对话","模型与聊天"],["file_interpret","文件解读","拖文件解读"],["vision","看看屏幕","视觉理解"],["proactive","主动识屏","主动陪伴"]]},
 {cat:"联动",items:[["agent_link","Agent 联动","Laji 事件提示音"],["dynamic_island","灵动岛","桌面胶囊"]]},
 {cat:"系统",items:[["quick_launch","快捷启动","菜单启动应用"],["stream_capture","直播捕获","捕获兼容"],["cross_screen","多屏跨屏","跨屏移动"],["system_tools","系统工具","系统级能力"]]}
];

/* ---------- 配置域 ---------- */
var DOMAINS=[
{id:"characters",name:"我的角色",ico:"🐾",desc:"角色包 / 人设",tabs:[
 {name:"角色卡",groups:[
  {title:"角色卡",fields:[{t:"packs",k:"character"}]}
 ]}
]},

{id:"general",name:"常规",ico:"⚙",desc:"启动 / 窗口 / 系统",tabs:[
 {name:"应用与启动",groups:[
  {title:"应用启动",fields:[
   t("autostart_wanted","开机自启",false,"全局 · 写系统登录项"),
   t("harness_autostart","随桌宠启动后台服务",false,"全局"),
   s("harness_launch_target","自启目标","auto","自动:auto|仅服务:service|网页:web|桌面:desktop"),
   t("show_dock_icon","显示 Dock 图标",true,"仅 macOS"),
   t("pet_persona_enabled","告诉 Laji 我是谁",true),
   act("恢复默认设置…","动作"),act("重置本宠设置…","动作"),act("重置全局设置…","动作")]},
  {title:"窗口与系统",fields:[
   t("on_top","窗口置顶",true),
   t("auto_hide_fullscreen","全屏时自动隐藏",true,"仅 Windows"),
   t("cursor_hidden_passthrough","光标隐藏时自动穿透",true,"仅 Windows"),
   t("stream_capture_mode","直播捕获兼容",false,"重启"),
   t("allow_cross_screen","允许桌宠跨屏",false,"重启"),
   note("直播捕获与跨屏是进程拓扑级开关，改完需要重启桌宠；跨屏还要求 overlay 渲染拓扑。")]},
 ]}
]},

{id:"pet",name:"桌宠",ico:"🐳",desc:"显示 / 动作 / 角色素材",tabs:[
 {name:"显示与音乐",groups:[
  {title:"桌宠显示",fields:[
   s("scale","桌宠大小",0.72,"小:0.5|标准:0.72|大:0.85|超大:1"),
   num("bubble_text_scale","气泡文字大小",100,50,300,10,"%"),
   num("pet_opacity","不透明度",100,10,100,1,"%")]},
  {title:"音乐关联",fields:[
   t("music_sing_enabled","音乐自动唱歌",false),
   t("music_lyric_enabled","显示歌词",false),
   num("music_lyric_lead_seconds","歌词提前量",1,0,10,0.5,"秒"),
   t("music_browser_media_enabled","浏览器媒体会话参与歌词",false,"仅 Windows"),
   t("foobar_lyrics_enabled","foobar2000 歌词",false,"仅 Windows"),
   x("foobar_title_format","播放器标题格式",""),
   x("music_player_paths.netease","网易云程序路径","","path"),
   x("music_player_paths.qqmusic","QQ 音乐程序路径","","path"),
   x("music_player_paths.kugou","酷狗程序路径","","path"),
   x("music_player_paths.soda","汽水程序路径","","path"),
   act("自动检测播放器","动作")]},
 ]},
 {name:"动作与碰撞",groups:[
  {title:"动画与移动",fields:[
   s("playback_speed","播放速率",1,"0.5×:0.5|0.75×:0.75|1×:1|1.25×:1.25|1.5×:1.5|2×:2|3×:3|4×:4"),
   num("animation_gap_seconds","动作等待间隔",0,0,3600,0.5,"秒"),
   t("idle_low_fps_enabled","省电模式",false),
   t("no_move","不移动",false),
   t("edge_probe_enabled","边缘探头",false)]},
  {title:"拖拽与弹射",fields:[
   t("drag_physics","拖动物理",false),
   t("drop_gravity","静止放手下落",false),
   s("throw_strength","甩出力度","standard","轻:gentle|标准:standard|用力:strong|狂野:crazy"),
   t("slingshot_enabled","弹弓弹射",true),
   t("lock_position","锁定位置",false),
   t("shift_drag","SHIFT + 左键拖动",false),
   t("spawn_inherit_size","生小肥鱼继承大小",true),
   s("spawn_scale","小肥鱼大小",0.72,"小:0.5|标准:0.72|大:0.85|超大:1"),
   act("一键退出子肥鱼","动作")]},
  {title:"多开碰撞",fields:[
   t("collision_enabled","碰撞开关",true),
   t("collision_sound_enabled","碰撞音效",true),
   num("collision_restitution","撞后弹力",0.82,0,1,0.01,""),
   num("collision_friction","摩擦系数",0.08,0,0.3,0.01,""),
   num("collision_mass_scale","体重倍率",1,0.5,2,0.1,""),
   num("collision_impulse_cap","最大撞击力度",9000,1000,12000,100,""),
   num("collision_sound_volume","碰撞音量",70,0,100,1,"%","存 0–1")]},
 ]}
]},

{id:"interaction",name:"互动",ico:"✦",desc:"点击 / 自言自语",tabs:[
 {name:"点击与音效",groups:[
  {title:"输入",fields:[t("mouse_through","鼠标穿透",false)]},
  {title:"点击反馈",fields:[
   t("click_sound_enabled","点击音效",true),
   s("click_sound_pack","音效音源","builtin","内置默认:builtin|内置鸭子:duck|单个音效文件:file|音效文件夹:folder"),
   x("click_sound_pack_path","音效文件 / 目录","","path"),
   num("click_sound_volume","音效音量",70,0,100,1,"%","存 0–1"),
   act("试听音效","动作"),
   t("click_show_balance","点击显示余额",false),
   t("click_show_self_talk","点击触发自言自语",false),
   t("self_talk_speak_enabled","点击台词朗读",false),
   t("self_talk_voice_precache_enabled","台词自动预缓存",false),
   act("点击动画台词绑定 · 编辑…","动作"),
   t("golden_spin_on_click","点击触发黄金回旋",false),
   t("golden_spin_direct","点击回旋跳过动画",false)]},
 ]},
 {name:"自言自语",groups:[
  {title:"气泡与节奏",fields:[
   s("self_talk_bubble_style","气泡方案","classic_top","经典暖黄:classic_top|纸张左侧:paper_left|玻璃右侧:glass_right|柔蓝上方:soft_blue_top|呼吸气泡:breath_bubble|靛紫声波:indigo_voice|靛紫夜:indigo_night"),
   t("self_talk_enabled","气泡自言自语",false),
   num("self_talk_duration_seconds","显示时间",3.2,1,300,0.1,"秒"),
   num("self_talk_min_interval","最短间隔",20,5,3600,1,"秒"),
   num("self_talk_max_interval","最长间隔",60,5,3600,1,"秒"),
   wide(x("self_talk_texts","候选内容（每行一条）","今天也要加油呀\n摸鱼一下也没关系吧\n要不要喝口水？\n我在这里陪着你\n伸个懒腰～","textarea")),
   x("self_talk_image_dir","配图目录","assets/big_blue_fat_fish","path"),
   num("self_talk_image_scale","配图大小",100,50,300,10,"%"),
   num("self_talk_image_chance","配图概率",30,0,100,5,"%")]},
  {title:"表达风格与台词",fields:[
   s("dialogue_mode","表达风格","legacy","默认模式:legacy|鲸鱼娘女仆:whale_maid|自定义台词:custom"),
   s("dialogue_last_scope","专属文案对象","","全局:|Agent A:agent-a|Agent B:agent-b"),
   wide(x("dialogue_phrases","逐事件气泡文案（开始工作 / 思考 / 读取文件 / 编辑代码 / 审批 / 完成…）","","textarea")),
   act("一键复制弹窗文案模板","动作"),act("导入模板","动作")]},
 ]},
]},

{id:"menu",name:"菜单",ico:"☰",desc:"菜单编排 / 快捷启动",tabs:[
 {name:"菜单编排",groups:[
  // k 不能省：client 的 fieldValue() 只按 f.k 去 catalogPrefs 里取值，
  // 少了它复合控件会拿到 undefined，退回插件内置模板（= 拿默认菜单覆盖用户布局）。
  {title:"内容与布局",fields:[{t:"menu",k:"context_menu_layout"}]},
  {title:"菜单入口",fields:[
   t("network_info_menu_enabled","显示「网络信息」菜单入口",true),
   t("menu_easter_egg.enabled","显示彩蛋入口",true),
   note("菜单编排写 context_menu_layout；与内置模板一致时写 null。改完 watcher 热生效，无需重启。未启用的功能模块对应菜单项会标为不可用，需在桌宠设置 → 功能里开启并重启。")
 ]}
 ]},
 {name:"快捷启动",groups:[
  {title:"已配置应用",fields:[{t:"list",k:"quick_launch_apps",label:"快捷启动应用",items:[{name:"默认浏览器",path:"",kind:"default_browser"}]}]}
 ]}
]},

{id:"chat",name:"AI 与对话",ico:"✧",desc:"模型服务与凭据",tabs:[
 {name:"模型",groups:[
  {title:"模型",fields:[wide(pr("chat_providers","模型"))]}
 ]}
]},

{id:"automation",name:"自动化与联动",ico:"⟳",desc:"提醒 / 主动识屏",tabs:[
 {name:"提醒与免打扰",groups:[
  {title:"待办提醒",fields:[
   t("todo_reminder_enabled","待办提醒",true),
   num("todo_reminder_lead_minutes","提前提醒",5,0,60,1,"分钟"),
   t("todo_reminder_speak","语音播报",false)]},
  {title:"免打扰与消息中心",fields:[
   s("quiet_minutes_default","默认时长",30,"15 分钟:15|30 分钟:30|1 小时:60|2 小时:120"),
   t("quiet_also_on_fullscreen","全屏应用时自动免打扰",true),
   s("approval_card_style","Laji 审批卡版式","glass","玻璃分段:glass|一次一张:focus"),
   s("open_app_pace","打开应用演出节奏","cinema","电影感:cinema|快速:quick|静默:silent"),
   note("审批卡版式保存后最多 7 秒生效，不用重启。")]}
 ]},
 {name:"主动识屏",groups:[
  {title:"总开关与节奏",fields:[
   t("proactive_screen.enabled","开启主动识屏",false),
   t("proactive_screen.dry_run","试运行（只记日志）",false),
   s("proactive_screen.preset","陪伴节奏预设","balanced","均衡:balanced|安静:quiet|积极:active|自定义:custom"),
   num("proactive_screen.dwell_seconds","同一窗口停留多久才看",45,15,600,5,"秒"),
   num("proactive_screen.cooldown_minutes","两次搭话至少间隔",5,1,120,1,"分钟"),
   num("proactive_screen.min_request_interval_seconds","两次识屏最短间隔",60,30,3600,10,"秒"),
   num("proactive_screen.daily_cap","每日请求上限",15,1,9999,1,"次"),
   act("从当前前台窗口添加…","动作"),act("清空陪伴记忆","动作")]},
  {title:"触发条件与白名单",fields:[
   t("proactive_screen.require_idle","仅当我闲置时触发",false),
   num("proactive_screen.min_idle_seconds","闲置判定秒数",30,5,3600,5,"秒"),
   t("proactive_screen.allow_when_mouse_through","鼠标穿透时仍识屏",true),
   t("proactive_screen.pre_cue","触发前先兆提示",true),
   t("proactive_screen.prefer_free_provider","识屏用单独的看图模型",true),
   wide(x("proactive_screen.whitelist","白名单（每行一条，进程名.exe 或 title:关键词）","","textarea"))]},
 ]}
]},

{id:"sound",name:"语音",ico:"♪",desc:"语音报时 / TTS / 节日提醒",tabs:[
 {name:"语音报时",groups:[
  {title:"基础设置",fields:[
   t("voice_chime_enabled","启用语音报时",false),
   s("voice_chime_schedule","报时频率","hourly","整点:hourly|每 30 分:every_30|每 15 分:every_15|每 5 分:every_5|每分钟:every_minute|自定义:custom"),
   x("voice_chime_custom_times","自定义时间点",""),
   num("voice_chime_volume","音量",80,0,100,1,"%"),
   t("voice_chime_show_bubble","报时气泡",true),
   t("voice_chime_show_quote","台词 / 歌词",true),
   act("立即试听","动作")]},
  {title:"台词",fields:[
   wide(x("voice_chime_custom_quotes_zh","自定义中文台词 / 歌词","","textarea")),
   wide(x("voice_chime_custom_quotes_en","自定义英文台词 / 歌词","","textarea"))]},
 ]},
 {name:"TTS 引擎",groups:[
  {title:"合成后端",fields:[
   s("voice_chime_tts_backend","语音引擎","edge","Edge 免 Key:edge|MiMo:mimo|系统 SAPI:sapi|豆包:doubao"),
   t("voice_chime_tts_fallback","失败自动回退",true),
   note("下面 4 组参数按所选引擎动态显示；API Key 类字段走钥匙串。"),
   s("voice_chime_voice","Edge 音色","zh-CN-XiaoxiaoNeural","晓晓:zh-CN-XiaoxiaoNeural|云希:zh-CN-YunxiNeural|晓伊:zh-CN-XiaoyiNeural"),
   num("voice_chime_rate","Edge 语速",0,-100,100,5,"%"),
   num("voice_chime_pitch","Edge 音调",0,-50,50,5,"Hz"),
   s("voice_chime_mimo_model","MiMo 模型","mimo-v2.5-tts","标准:mimo-v2.5-tts|音色设计:mimo-v2.5-voicedesign"),
   x("voice_chime_mimo_voice","MiMo 音色","冰糖"),
   x("voice_chime_mimo_api_key","MiMo API Key","","password","钥匙串"),
   x("voice_chime_sapi_voice","SAPI 嗓音",""),
   num("voice_chime_sapi_rate","SAPI 语速",0,-10,10,1,""),
   x("voice_chime_doubao_speaker","豆包音色","zh_female_peiqi_uranus_bigtts"),
   num("voice_chime_doubao_pitch","豆包音调",15,0,30,1,""),
   x("voice_chime_doubao_api_key","豆包 API Key","","password","钥匙串")]}
 ]},
 {name:"节日提醒",groups:[
  {title:"何时提醒",fields:[
   t("festival_reminder_enabled","启用节日提醒",false),
   s("festival_reminder_mode","提醒方式","times","按次数:times|自定义时间:custom"),
   num("festival_reminder_count","每天提醒几次",2,1,6,1,"次"),
   x("festival_reminder_times","自定义提醒时间","09:00"),
   x("festival_birthday","我的生日",""),
   act("立即试听","动作")]},
  {title:"提醒哪些日子 / 怎么提醒",fields:[
   t("festival_reminder_cn","中国节日",true),
   t("festival_reminder_solar_terms","24 节气",true),
   t("festival_reminder_west","西方节日",true),
   t("festival_reminder_speak","语音播报",false),
   t("festival_reminder_animation","节日动画",true),
   t("festival_reminder_show_quote","附带文案",true),
   wide(x("festival_custom_quotes_cn","自定义中文文案","","textarea")),
   wide(x("festival_custom_quotes_west","自定义西文文案","","textarea"))]},
 ]}
]},

{id:"file",name:"文件识别",ico:"▣",desc:"拖文件解读",tabs:[
 {name:"拖文件解读",groups:[{title:"文件识别",fields:[
   t("file_interpret.enabled","拖文件后询问解读",true),
   num("file_interpret.progress_interval_seconds","进度汇报间隔",15,5,120,1,"秒"),
   note("该模块整域随 feature_activation 的 file_interpret 开关显示 / 隐藏。")
 ]}]}
]}
];
// ---------------------------------------------------------------- 元数据

/** 目录整体（经 /api/state 原样发给前端）。 */
export const CATALOG = { domains: DOMAINS, menuNodes: MENU_NODES, features: FEATURES };

/**
 * 每宠键：真值在 config-slot-0.json。镜像 pet/pet_profiles.py 的
 * PER_PET_SETTING_KEYS + 朝向/位置/本地键，改动要与那边同步。
 */
export const SLOT_KEYS = new Set([
  "scale", "playback_speed", "drag_physics", "drop_gravity", "throw_strength",
  "ffmpeg_recycle_minutes", "click_sound_enabled", "click_sound_volume",
  "click_sound_pack", "click_sound_pack_path", "collision_sound_enabled",
  "collision_sound_volume", "collision_enabled", "self_talk_enabled",
  "self_talk_texts", "self_talk_duration_seconds", "self_talk_image_dir",
  "self_talk_image_scale", "self_talk_image_chance", "self_talk_min_interval",
  "self_talk_max_interval", "self_talk_speak_enabled", "self_talk_bubble_style",
  "bubble_text_scale", "click_show_balance", "click_show_self_talk",
  "roleplay_enabled", "roleplay_scene", "roleplay_cast", "character",
  "facing", "rx", "ry", "screen_name", "user_customized",
]);

/** 功能卡登记的模块 id（保存 feature_activation 时只替换这一组，别抹掉桌宠侧其它模块）。 */
export const FEATURE_IDS = FEATURES.flatMap((cat) => cat.items.map((it) => it[0]));

const SKIP_TYPES = new Set(["action", "note", "readonly"]);

/** 把目录拍平成可写字段表；复合控件用 compound 标出，密钥用 secret 标出。 */
export function collectFields(catalog = CATALOG) {
  const out = [];
  for (const d of catalog.domains || []) {
    for (const tab of d.tabs || []) {
      for (const group of tab.groups || []) {
        for (const f of group.fields || []) {
          if (!f || SKIP_TYPES.has(f.t)) continue;
          let key = f.k;
          let type = f.t;
          let compound = null;
          if (f.t === "packs") { key = "character"; type = "packs"; compound = "packs"; }
          else if (f.t === "menu") { key = "context_menu_layout"; type = "menu"; compound = "menu"; }
          else if (f.t === "features") { key = "feature_activation"; type = "features"; compound = "features"; }
          else if (f.t === "list") { type = "list"; compound = "list"; }
          else if (f.t === "providers") { type = "providers"; compound = "providers"; }
          if (!key) continue;
          const head = String(key).split(".")[0];
          out.push({
            key, label: f.l || "", type, def: f.d, min: f.min, max: f.max,
            step: f.step, options: f.o || null, unit: f.u || "", note: f.n || "",
            compound, slot: SLOT_KEYS.has(head), dotted: key.includes("."),
            // max_tokens 是数值、api_key_ref 是钥匙串引用名，都不是密钥本体。
            secret: type === "password" ||
              (/(^|[._-])(api_key|apikey|secret|password)($|[._-])/.test(key) &&
                !/api_key_ref|max_tokens/.test(key)),
          });
        }
      }
    }
  }
  return out;
}

export const CATALOG_FIELDS = collectFields();
export const FIELD_BY_KEY = new Map(CATALOG_FIELDS.map((f) => [f.key, f]));

/** UI 口径默认值（range/number 的 def 已是 0-100 百分比，不落盘时不换算）。 */
export function catalogDefaults() {
  return Object.fromEntries(CATALOG_FIELDS.map((f) => [f.key, f.def]));
}

/** 目录规模，给测试与诊断用。 */
export function catalogStats() {
  let tabs = 0;
  let items = 0;
  for (const d of CATALOG.domains) {
    tabs += (d.tabs || []).length;
    for (const tab of d.tabs || []) {
      for (const group of tab.groups || []) {
        for (const f of group.fields || []) {
          if (!f || f.t === "note") continue;
          if (f.t === "action") continue;
          if (f.t === "features") items += 16;
          else if (f.t === "menu") items += 62;
          else if (f.t === "packs") items += 5;
          else if (f.t === "list") items += (f.items || []).length;
          else items += 1;
        }
      }
    }
  }
  return { domains: CATALOG.domains.length, tabs, items, fields: CATALOG_FIELDS.length };
}
