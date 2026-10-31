/*
 * Copyright (c) 2019, Kudo, Inc.
 * All rights reserved.
 *
 * Author: Duke Fong <d@d-l.io>
 */

// cat zh_cn.js | cconv -f UTF8 -t UTF8-HK
let trans_zh_hk = {
    'Language': '語言',
    'Auto': '自動',
    'Load': '加載',
    'Export': '導出',
    'Import': '導入',
    'Project': '工程',
    'Reset': '復位',
    'Config': '配置',
    'Save': '保存',
    
    'Cur pos': '當前位置',
    'Aux pos': '輔助位置',
    'Reset aux': '清零輔助位置',
    
    'Up': '上升',
    'Down': '下降',
    'CCW': '逆時針旋轉',
    'CW': '順時針旋轉',
    
    'Step size': '移動步進',
    'Motor speed': '電機速度',
    
    'Less detect': '減少探高次數',
    
    'Show target': '顯示目標位置',
    'Goto comp': '移至取料',
    'Snap': '鎖定',
    'Pickup': '吸取',
    'Check': '檢查',
    'Goto pcb': '移至 pcb',
    'Put down': '放置',
    
    'Pause': '暫停',
    'Stop': '停止',
    'Run': '運行',
    
    'Enable pump': '使能氣泵',
    
    'Camera': '相機',
    'Default': '預設',
    'Limit angle': '限制角度',
    'None': '無',
    'Cali nozzle': '校準吸嘴',
    
    'Enable': '使能',
    'Light': '照明',
    
    'New BG': '更新背景',
    'Del BG': '刪除背景',
    
    '2nd check': '二次檢查',
    
    'Calibration': '校準',
    'Cam angle err': '相機角度誤差',
    'Cam scale': '相機比例',
    'Update cam scale': '更新相機比例',
    'max error': '最大誤差',
    'Camera scale calibration failed: no part found, or it was lost on the way': '相機比例標定失敗：沒有找到元件，或移動途中丟失了元件',
    'Snap on a part at the comp search position, then move around it out to the edge of the frame and measure': '在元件搜尋位置鎖定一顆元件，然後圍繞它移動到畫面邊緣逐點測量',
    'edge': '邊緣',
    'samples': '個樣本',
    'mm per pixel of camera 1, from its calibration; edge: how much more (+) or less a pixel is worth at the corner of the frame': '相機 1 每像素的毫米數，來自其標定；邊緣：畫面角落的像素比中心多 (+) 或少多少',
    'Put a single part at': '請只放一顆元件在',
    'and remove the others, so the camera can follow it to the edge of the frame. Start?': '並移走其它元件，以便相機能跟隨它到畫面邊緣。開始？',
    'Forget the measured camera scale and start again from 10/344 mm per pixel?': '清除已測得的相機比例，重新從 10/344 mm/像素開始？',
    'Cali cam': '校準相機',
    
    'Exposure': '爆光',
    'Threshold': '閾值',
    
    'Debug': '調試',
    'Set': '設置',
    
    'Grab offset': '眼嘴偏移',
    'Nozzle cali': '旋轉誤差',
    
    'Camera delta z': '相機 dz (嘴到地)',
    'Comp base z': '取料地面',
    'PCB base z': 'PCB 放料地面',
    'Cur': '當前',
    
    'Comp base': '取料地面',
    'PCB base': 'PCB 地面',
    'Detect bottom': '探測底高',
    
    'Fiducial pcb': '定位點 PCB 座標',
    
    'Goto': '跳轉',
    'Update': '更新',
    'Select': '選擇',
    
    'Comp search': '元件搜尋',
    'Fiducial cam': '定位點 CAM',
    'User pos': '用戶位置',
    
    'Preload': '預加載',
    'Preload search': '預加載搜尋',
    'Preload base z': '預加載地面',
    'Preload base': '預加載地面',
    'Comp offset': '元件偏移',
    'Comp space': '元件間距',
    'Start at': '開始位置',
    'unit': '單位',
    'Target grid': '目標網格',
    'Rotate': '旋轉',
    'Count': '數量',
    'Clear': '清除',
    
    'Components': '元件列表',
    'Current': '當前',
    'Height': '高度',
    'Tray comps': '料盤元件',
    'The parts seen at the comp search position, the run goes to them one by one': '在元件搜尋位置看到的元件，運行時逐個前往',
    'found': '個已記錄',
    'left': '個待取',
    'picked': '個已取',
    'lost': '個丟失',
    'fail': '個失敗',
    'odd size': '個尺寸異常',
    'The frame at the search position: blue left, orange current, green picked, grey lost, red fail; the black cross is the camera now': '搜尋位置的畫面縮略圖：藍 待取，橙 當前，綠 已取，灰 丟失，紅 失敗；黑色十字是相機當前位置',
    'ref size': '參考尺寸',
    'median': '中位數',
    'Next': '下一個',
    'Amount': '數量',
    'total': '總計',
    
    'Footprint': '封裝',
    'Offset': '偏移',
    'Value': '取值',
    'Reference': '標號',
    
    'Offsets': '偏移',
    'Apply': '應用',
    'or refresh page': '或刷新頁面',
    
    'Saved.': '已保存。',
    'Ok, please save config and refresh page.': '成功，請保存配置和刷新頁面。',
    'Format error': '格式錯誤',
    'Import config succeeded': '導入配置成功',
    'Import project succeeded': '導入工程成功',
    'Apply OK.': '應用成功。',
    'please set camera vision detect method!': '請選擇一個視覺探測方式！',
    'list empty!': '列表為空',
    'please stop smt first!': '請先停止 smt!',
    'please set camera vision detect method for nozzle calibration!': '請選擇符合吸嘴探測的視覺方式！',
    
    'Distance from the camera center to the nozzle rotation center': '相機中心 到 吸嘴旋轉中心 的位移',
    'Offset from the nozzle rotation center to nozzle at 0 degrees': '吸嘴旋轉中心 到 吸嘴位於 0 度時的偏移',
    'Height of nozzle to target when focusing (better not modify this)': '相機對焦時，吸嘴到目標的高度 (建議不要修改)',
    'Fiducial coordinates in PCB file': '定位點在 PCB 軟件中的座標',
    
    // websocket banner
    'The page is already opened in another window, only one page is allowed.': '頁面已在其他窗口打開中，只能打開一個頁面。',
    'Close this window and use the existing one. (If the existing one was just closed, wait a few seconds and reload.)': '請關閉本窗口，使用已打開的窗口。（如果已打開的窗口剛剛關閉，請等幾秒後刷新本頁。）',
    'WebSocket disconnected': 'WebSocket 已斷開',
    'The backend may have exited or the connection was lost, please check the backend log and reload the page.': '後台程序可能已退出或連接已斷開，請檢查後台日誌後刷新頁面。'
};

export { trans_zh_hk };
