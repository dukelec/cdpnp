/*
 * Copyright (c) 2019, Kudo, Inc.
 * All rights reserved.
 *
 * Author: Duke Fong <d@d-l.io>
 */

// cat zh_hk.js | cconv -f UTF8 -t UTF8-CN
let trans_zh_cn = {
    'Language': '语言',
    'Auto': '自动',
    'Load': '加载',
    'Export': '导出',
    'Import': '导入',
    'Project': '工程',
    'Reset': '复位',
    'Config': '配置',
    'Save': '保存',
    
    'Cur pos': '当前位置',
    'Aux pos': '辅助位置',
    'Reset aux': '清零辅助位置',
    
    'Up': '上升',
    'Down': '下降',
    'CCW': '逆时针旋转',
    'CW': '顺时针旋转',
    
    'Step size': '移动步进',
    'Motor speed': '电机速度',
    
    'Less detect': '减少探高次数',
    
    'Show target': '显示目标位置',
    'Goto comp': '移至取料',
    'Snap': '锁定',
    'Pickup': '吸取',
    'Check': '检查',
    'Goto pcb': '移至 pcb',
    'Put down': '放置',
    
    'Pause': '暂停',
    'Stop': '停止',
    'Run': '运行',
    
    'Enable pump': '使能气泵',
    
    'Camera': '相机',
    'Default': '默认',
    'Limit angle': '限制角度',
    'None': '无',
    'Cali nozzle': '校准吸嘴',
    
    'Enable': '使能',
    'Light': '照明',
    
    'New BG': '更新背景',
    'Del BG': '删除背景',
    
    '2nd check': '二次检查',
    
    'Calibration': '校准',
    'Cam angle err': '相机角度误差',
    'Cam scale': '相机比例',
    'Update cam scale': '更新相机比例',
    'max error': '最大误差',
    'Camera scale calibration failed: no part found, or it was lost on the way': '相机比例标定失败：没有找到元件，或移动途中丢失了元件',
    'Snap on a part at the comp search position, then move around it out to the edge of the frame and measure': '在元件搜寻位置锁定一颗元件，然后围绕它移动到画面边缘逐点测量',
    'edge': '边缘',
    'samples': '个样本',
    'mm per pixel of camera 1, from its calibration; edge: how much more (+) or less a pixel is worth at the corner of the frame': '相机 1 每像素的毫米数，来自其标定；边缘：画面角落的像素比中心多 (+) 或少多少',
    'Put a single part at': '请只放一颗元件在',
    'and remove the others, so the camera can follow it to the edge of the frame. Start?': '并移走其它元件，以便相机能跟随它到画面边缘。开始？',
    'Forget the measured camera scale and start again from 10/344 mm per pixel?': '清除已测得的相机比例，重新从 10/344 mm/像素开始？',
    'Cali cam': '校准相机',
    
    'Exposure': '爆光',
    'Threshold': '阈值',
    
    'Debug': '调试',
    'Set': '设置',
    
    'Grab offset': '眼嘴偏移',
    'Nozzle cali': '旋转误差',
    
    'Camera delta z': '相机 dz (嘴到地)',
    'Comp base z': '取料地面',
    'PCB base z': 'PCB 放料地面',
    'Cur': '当前',
    
    'Comp base': '取料地面',
    'PCB base': 'PCB 地面',
    'Detect bottom': '探测底高',
    
    'Fiducial pcb': '定位点 PCB 座标',
    
    'Goto': '跳转',
    'Update': '更新',
    'Select': '选择',
    
    'Comp search': '元件搜寻',
    'Fiducial cam': '定位点 CAM',
    'User pos': '用户位置',
    
    'Preload': '预加载',
    'Preload search': '预加载搜寻',
    'Preload base z': '预加载地面',
    'Preload base': '预加载地面',
    'Comp offset': '元件偏移',
    'Comp space': '元件间距',
    'Start at': '开始位置',
    'unit': '单位',
    'Target grid': '目标网格',
    'Rotate': '旋转',
    'Count': '数量',
    'Clear': '清除',
    
    'Components': '元件列表',
    'Show deleted': '显示已删除',
    'Delete': '删除',
    'Restore': '恢复',
    'Delete all of this value': '删除这个值的全部元件',
    'Restore all of this value': '恢复这个值的全部元件',
    'The run is on this part, select another part first': '正在运行这个元件，请先选择其它元件',
    'Current': '当前',
    'Height': '高度',
    'Tray comps': '料盘元件',
    'The parts seen at the comp search position, the run goes to them one by one': '在元件搜寻位置看到的元件，运行时逐个前往',
    'found': '个已记录',
    'left': '个待取',
    'picked': '个已取',
    'lost': '个丢失',
    'fail': '个失败',
    'odd size': '个尺寸异常',
    'The frame at the search position: blue left, orange current, green picked, grey lost, red fail; the black cross is the camera now': '搜寻位置的画面缩略图：蓝 待取，橙 当前，绿 已取，灰 丢失，红 失败；黑色十字是相机当前位置',
    'ref size': '参考尺寸',
    'median': '中位数',
    'Next': '下一个',
    'Amount': '数量',
    'total': '总计',
    
    'Footprint': '封装',
    'Offset': '偏移',
    'Value': '取值',
    'Reference': '标号',
    
    'Offsets': '偏移',
    'Apply': '应用',
    'or refresh page': '或刷新页面',
    
    'Saved.': '已保存。',
    'Ok, please save config and refresh page.': '成功，请保存配置和刷新页面。',
    'Format error': '格式错误',
    'Import config succeeded': '导入配置成功',
    'Import project succeeded': '导入工程成功',
    'Apply OK.': '应用成功。',
    'please set camera vision detect method!': '请选择一个视觉探测方式！',
    'list empty!': '列表为空',
    'please stop smt first!': '请先停止 smt!',
    'please set camera vision detect method for nozzle calibration!': '请选择符合吸嘴探测的视觉方式！',
    
    'Distance from the camera center to the nozzle rotation center': '相机中心 到 吸嘴旋转中心 的位移',
    'Offset from the nozzle rotation center to nozzle at 0 degrees': '吸嘴旋转中心 到 吸嘴位于 0 度时的偏移',
    'Height of nozzle to target when focusing (better not modify this)': '相机对焦时，吸嘴到目标的高度 (建议不要修改)',
    'Fiducial coordinates in PCB file': '定位点在 PCB 软件中的座标',
    
    // websocket banner
    'The page is already opened in another window, only one page is allowed.': '页面已在其他窗口打开中，只能打开一个页面。',
    'Close this window and use the existing one. (If the existing one was just closed, wait a few seconds and reload.)': '请关闭本窗口，使用已打开的窗口。（如果已打开的窗口刚刚关闭，请等几秒后刷新本页。）',
    'WebSocket disconnected': 'WebSocket 已断开',
    'The backend may have exited or the connection was lost, please check the backend log and reload the page.': '后台程序可能已退出或连接已断开，请检查后台日志后刷新页面。'
};

export { trans_zh_cn };
