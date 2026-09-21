.PHONY: test demo

test:
	python3 -m unittest discover -s tests -v

demo:
	python3 -m should_i_jev --demo --report demo-report.md --html demo-dashboard.html
