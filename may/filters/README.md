# Filter Files Directory

This directory contains filter files for loading specific geographical units.

## File Format

Filter files are simple text files with one code per line:

```
E02000173
E02000187
E02000414
E02000415
```

## Comments

Lines starting with `#` are treated as comments and ignored:

```
# This is a comment
E02000173
E02000187
```

## Usage

### In config.yaml:
```yaml
mgu_filter:
  codes: []
  file: "filters/my_mgus.txt"
```

### Via command line:
```bash
python create_world.py --mgu-file filters/my_mgus.txt
```

## Examples

- `example_mgu.txt`: Example Medium Geographical Unit filter
- Create your own filter files for LGU, MGU, or SGU levels
