/*
 * Software License Agreement (MIT License)
 *
 * Author: Waters Tang <waters_tang@bitspace.ltd>
 */

import { read_file, download, readable_float, cpy, sleep, wildcard_test } from './utils/helper.js';
import { csv_to_pos, pos_to_page } from './pos_list.js'

let layer_selection_modal = document.getElementById("modal_load_altium_csv");
let modalLayersButtonsContainer = document.getElementById("load_altium_csv_modal_buttons_container");

var csvObject;

document.getElementById('btn_load_altium_csv').onclick = async function() {
    console.log('load_altium_csv');

    //let input = document.createElement('input');
    //cpy(input, {type: 'file', accept: '*.cdg'}, ['type', 'accept']);
    let input = document.getElementById('input_file');
    input.accept = '.csv';
    input.onchange = async function () {
        var files = this.files;
        if (files && files.length) {
            let file = files[0];
            let data_str = await readANSIToUTF8(file);

            //以下删除Altium的文件头，要求文件头中必须有以下列，否则无法进行转换
            var csvData = data_str.split('\r\n');
            var filteredRows = csvData.filter(function(row) {
                var keywords = ['Designator', 'Comment', 'Footprint', 'Center-X(mm)', 'Center-Y(mm)', 'Rotation', 'Layer'];
                return keywords.every(function(keyword) {
                    return row.includes(keyword);
                });
            });
            var rowIndex = csvData.findIndex(function(row) {
                return row === filteredRows[0];
            });
            if (rowIndex == -1) {
                alert("The Pick and Place file must contains the following information: \r\nDesignator\r\nComment\r\nFootprint\r\nCenter-X(mm)\r\nCenter-Y(mm)\r\nRotation\r\nLayer\r\nThe selected file has missing information.");
                return;
            }
            csvData.splice(0, rowIndex);

            //以下删除多余的空行，因为Description中可能存在空行，输出是在csv文件中也会被保留，需要删除
            for (var i = 0; i < csvData.length - 1; i++) {
                var currentRow = csvData[i];
                var nextRow = csvData[i + 1];

                if (currentRow[currentRow.length - 1] !== '"') {
                    csvData[i] = currentRow.trim() + nextRow.trim();
                    csvData.splice(i + 1, 1);
                    i--; // 调整索引，以便处理合并后的行
                }
            }

            //以下解析Altium的CSV，便于处理数据
            let config = buildConfig();
            csvObject = Papa.parse(csvData.join('\r\n'), config);

            //以下处理数据，并生成一个新的CSV String，符合KiCad格式，随后交给常规的导入函数进行导入
            var layers = new Set();
            for (let elm of csvObject.data) {
                layers.add(elm.Layer);
                //底层的话还要修改座标文件，把所有 X 轴数据取反
                /*
                if (elm.Layer == "BottomLayer") {
                    elm['Center-X(mm)'] = elm['Center-X(mm)'] * -1
                }
                */
                //实际测得不需要取反
            }

            //以下处理当CSV中存在多个Layer时，让用户选择需要导入的Layer
            if (layers.size == 1) {
                createKicadCSVString(Array.from(layers)[0]);
            } else {
                modifyAndShowLayerOptions(layers);
            }
            console.log(csvObject);
            console.log(layers);

        }
        this.value = '';
    };
    input.click();
};

function buildConfig() {
	return {
		delimiter: "",
		header: true,
		dynamicTyping: true,
		skipEmptyLines: true,
		worker: false
	};
}

function modifyAndShowLayerOptions(layers) {
    // 清空旧的选项按钮
    modalLayersButtonsContainer.innerHTML = "";

    for (let layer of layers) {
        var layerButton = document.createElement("button");
        layerButton.className = "load_altium_csv_modal_button";
        layerButton.textContent = layer;
        layerButton.addEventListener("click", handleLayerOptionButtonOnClick.bind(null, layer));
        layerButton.addEventListener("mouseenter", function() {
            this.classList.add('hovered');
        });
        layerButton.addEventListener("mouseleave", function() {
            this.classList.remove('hovered');
        });
        modalLayersButtonsContainer.appendChild(layerButton);
    }

    layer_selection_modal.style.display = "block";
}

function handleLayerOptionButtonOnClick(layer) {
    layer_selection_modal.style.display = "none";
    createKicadCSVString(layer);
}

function createKicadCSVString(layer = "") {
    var inuseCSVData;
    if (layer != "") {
        inuseCSVData = csvObject.data.filter(obj => obj.Layer == layer);
    } else {
        inuseCSVData = csvObject.data
    }

    var kicadString = "";
    kicadString += "Ref,Val,Package,PosX,PosY,Rot,Side"
    for (let elm of inuseCSVData) {
        kicadString += "\r\n";
        kicadString += "\"" + elm.Designator + "\",";
        kicadString += "\"" + elm.Comment + "\",";
        kicadString += "\"" + elm.Footprint + "\",";
        kicadString += elm['Center-X(mm)'] + ",";
        kicadString += elm['Center-Y(mm)'] + ",";
        kicadString += elm.Rotation + ",";
        kicadString += elm.Layer;
    }

    //显示关于Fiducial的提示文字
    let waring_text = document.getElementById("fiducial_warning_message");
    waring_text.innerHTML = `Simply copy the coordinates from the table below. <a href="https://github.com/dukelec/cdpnp/discussions/5" target="_blank">Documentation</a> is here.`;
    /*
    if (layer == "BottomLayer") {
        //底层的话，要在 CDPnP 软件界面，把参考点 PCB 文件座标 X 和 Y 轴都取反
        waring_text.innerHTML = "CSV from Altium, using BottomLayer, you should inverse both X-axis and Y-axis value of markers.";
    } else if (layer == "TopLayer") {
        //顶层的话，要在 CDPnP 软件界面，把参考点 PCB 文件座标 Y 轴取反
        waring_text.innerHTML = "CSV from Altium, using TopLayer, you should inverse Y-axis value of markers.";
    }
    */
    waring_text.style.display = "inline-block";

    importAltiumCSVFinalStep(kicadString);
}

function importAltiumCSVFinalStep(kicadString) {
    let pos = csv_to_pos(kicadString);
    console.log('load pos:', pos);
    pos_to_page(pos);
    document.getElementById('btn_save_cfg').style.background = 'yellow';
}

//由于Altium输出的CSV编码为GBK，所以需要转换为utf-8进行读取，中文才不会乱码
async function readANSIToUTF8(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = function(event) {
      const content = event.target.result;
      const ansiDecoder = new TextDecoder('GBK');  // 将解码字符集更改为 GBK

      const ansiText = ansiDecoder.decode(content);

      resolve(ansiText);
    };

    reader.onerror = function() {
      reject(new Error("Failed to read the file."));
    };

    reader.readAsArrayBuffer(file);
  });
}