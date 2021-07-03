
cut_len_x = 0.877 + (0.4 * 2)
cut_len_y = 0

sub_delta = (10, 11.3)
sub_first = [(7.0-0.4, -50.2-0.1), (14.123-0.4, -50.2-0.1), (7.0-0.4, -40.9+0.1), (14.123-0.4, -40.9+0.1)]

for ix in range(5):
    for iy in range(4):
        for p in sub_first:
            pos.append((p[0] + sub_delta[0] * ix, p[1] + sub_delta[1] * iy))


pcb_base_z = -84.8-0.2

fiducial_pcb = [ [7, -7], [55, -7] ]
fiducial_cam = [
    [235.615, 182.641],
    [283.515, 182.941]
]

#print(pos)

