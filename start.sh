#!/bin/bash

which gnome-terminal 2> /dev/null && XTERM=gnome-terminal
which xfce4-terminal 2> /dev/null && XTERM=xfce4-terminal
[ "$TERM" == "" ] && exit -1

tty -s; if [ $? -ne 0 ]; then $XTERM -e "\"$0\"" --title="CDPNP GUI Tool"; exit; fi

cd "$(dirname "$(realpath "$0")")"

function anykey_exit()
{
  read -n1 -r -p "Press any key to exit..."
  exit
}

./pnp_main.py -d

anykey_exit

