# Expense Tracker

A command-line expense tracker built with Python's standard library.

## Features

- Add expenses with category, description, and amount
- Store expenses in a JSON file
- List all saved expenses
- Show total and totals by category
- Uses `decimal.Decimal` for exact currency calculations (max 2 decimal places)
- Safe handling of invalid amounts and malformed JSON

## Installation

No installation required. This tool uses only Python's standard library.

## Usage

### Add an expense

```bash
python expense_tracker.py --file expenses.json add food "Lunch" 12.50
```

### List expenses

```bash
python expense_tracker.py --file expenses.json list
```

### Show summary

```bash
python expense_tracker.py --file expenses.json summary
```

## Command Line Options

- `--file PATH`: Path to the JSON file storing expenses (default: `expenses.json`)

## Examples

```bash
# Add a food expense
python expense_tracker.py --file expenses.json add food "Lunch" 12.50

# List all expenses
python expense_tracker.py --file expenses.json list

# Show summary with totals
python expense_tracker.py --file expenses.json summary
```

## Safety Features

- Rejects zero, negative, nonnumeric, and overprecision amounts
- Never overwrites malformed JSON data
- Uses temporary files for safe writes

## Testing

Run tests with:

```bash
python -m unittest discover -v
```

All tests use temporary directories and require no internet or extra packages.
