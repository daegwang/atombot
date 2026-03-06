#!/bin/bash
# Count atombot core lines
cd "$(dirname "$0")" || exit 1

echo "atombot core line count"
echo "================================"
echo ""

base="atombot"
files=$(find "$base" -type f -name "*.py" ! -path "$base/cli/*" ! -name "__main__.py" ! -name "__init__.py" | sort)

if [ -n "$files" ]; then
  while IFS= read -r path; do
    file="${path#"$base/"}"
    count=$(wc -l < "$path")
    printf "  %-24s %5s lines\n" "$file" "$count"
  done <<EOF
$files
EOF
fi

echo ""
if [ -d "$base" ]; then
  total=$(find "$base" -type f -name "*.py" ! -path "$base/cli/*" ! -name "__main__.py" ! -name "__init__.py" -exec cat {} + | wc -l)
else
  total=0
fi
echo "  Core total:     $total lines"

echo ""
echo "  (target: atombot/**/*.py, excluding atombot/cli/*, __main__.py, and __init__.py)"
