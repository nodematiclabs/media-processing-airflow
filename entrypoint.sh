#!/bin/bash

set -e

gsutil cp "gs://$BUCKET/$INPUT_FILE" "$INPUT_FILE"
eval ffmpeg -i \"$INPUT_FILE\" $TRANSFORMATIONS \"$OUTPUT_FILE\"
gsutil cp "$OUTPUT_FILE" "gs://$BUCKET/$OUTPUT_FILE"