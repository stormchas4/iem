#!/bin/sh
#echo -e "Content-type: text/plain\n\n"
#echo -e "\n"
#exit 0

MS_MAPFILE=/opt/iem/data/wms/goes/conus_wv.map
export MS_MAPFILE

/opt/iem/cgi-bin/mapserv/mapserv
