find . -path ./venv -prune -o -type f -name "00??_*.py" -exec rm {} \;
