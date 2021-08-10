MAKEFLAGS += --silent

total-lot:
	cat stock-selections.json | jq 'map(.lot) | add'
