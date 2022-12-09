#!/bin/bash

# converts all osz files in current directory
for f in *.osz; do
	python chart_mania.py -d "$1" -z "$f"
done
