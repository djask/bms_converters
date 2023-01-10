#!/bin/bash

SCRIPT="chart_mania.py"
OUTPUT_DIR=""
SRC_DIR="."
OPERATION=""

if [ -z ${BMS_OFFSET+x} ]; then
	echo "using default OFFSET";
	BMS_OFFSET=60
else 
	echo "using OFFSET '$BMS_OFFSET'";
fi

usage() {
	echo "
	usage $0
	-o	{default to .)output BMS dir
	-s	{default to .)source osz dir
	-a	Convert all osz files in directory
	-w	Watches directory for new osz files
	"
}

while getopts ":awo:s:" o; do
	case "${o}" in
	a)
		OPERATION="convert_all"
		;;
	w)
		OPERATION="convert_watch"
		;;
	o)
		OUTPUT_DIR=$OPTARG
		;;
	s)
		SRC_DIR=$OPTARG
		;;
	*)
		usage
		;;
    esac
done
shift $((OPTIND-1))


echo $OUTPUT_DIR

convert_watch() {
	echo "watch $SRC_DIR"
	inotifywait -m "$SRC_DIR" -e moved_to *.osz | 
	while read -r dir event f; do
		python $SCRIPT -d "$OUTPUT_DIR" -z "$f" -o $BMS_OFFSET
	done
}

convert_all() {
	for f in *.osz; do
		python $SCRIPT -d "$OUTPUT_DIR" -z "$f" -o $BMS_OFFSET
	done
}



if [ OPERATION == "" ]; then
	echo "No operation provided, exiting"
	exit 1
fi


eval $OPERATION
