
kicad bottom layer:
 - fiducial pcb x * -1
 - enable `Use negative X coordinates for footprints on bottom layer` in `Generate Placement Files`

ad, allegro top layer:
 - fiducial pcb y * -1

ad, allegro bottom layer:
 - fiducial pcb x * -1 and y * -1
 - csv file all items: x * -1 (by `csv_conv_xxx.py`)

