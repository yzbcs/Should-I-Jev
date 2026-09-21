.PHONY: test demo calib migrate

test:
	python3 -m unittest discover -s tests -v

demo:
	python3 -m should_i_jev --demo --jev-selfcheck --report demo-report.md --html demo-dashboard.html

calib:
	python3 -m should_i_jev calibrate should_i_jev/fixtures/calibration/decisions_jev.jsonl \
		--baseline should_i_jev/fixtures/calibration/decisions_llm.jsonl \
		--report demo-calibration.md --html demo-calibration.html

migrate:
	python3 -m should_i_jev migrate --scan-code should_i_jev/fixtures/sample_code
