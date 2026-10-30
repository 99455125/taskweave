"""Build the shipped regular font; fontTools is a build-time tool only.

Run with uv run --no-project --with fonttools python plugins/pdf/tools/prepare_font.py SOURCE.ttf.
Source: https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf
SHA256: a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da
The resulting derivative keeps the original OFL; its name does not use the reserved name Source.
"""
import hashlib
import json
import zlib
from pathlib import Path
import sys
from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


def main():
    source = Path(sys.argv[1])
    if hashlib.sha256(source.read_bytes()).hexdigest() != 'a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da':
        raise ValueError('Unexpected source font; review upstream changes before regenerating')
    font = instantiateVariableFont(TTFont(source, recalcTimestamp=False), {'wght': 400}, inplace=True)
    options = subset.Options()
    options.hinting = False
    options.layout_features = []
    options.name_IDs = ['*']
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=font.getBestCmap())
    subsetter.subset(font)
    for name_id, value in ((1, 'TaskWeave PDF Sans'), (2, 'Regular'), (3, 'TaskWeavePDFSans-Regular'),
                           (4, 'TaskWeave PDF Sans Regular'), (6, 'TaskWeavePDFSans-Regular')):
        font['name'].setName(value, name_id, 3, 1, 0x409)
    destination = Path(__file__).resolve().parents[1] / 'src/taskweave_pdf/fonts/TaskWeavePDFSans-Regular.ttf'
    font.save(destination)
    write_metrics(destination)
    print(destination, destination.stat().st_size)


def write_metrics(destination):
    # Runtime uses this compact mapping instead of importing fontTools.
    with TTFont(destination) as font:
        metrics = {
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
            'units_per_em': font['head'].unitsPerEm,
            'ascent': font['hhea'].ascent, 'descent': font['hhea'].descent,
            'characters': {str(code): [font.getGlyphID(name), font['hmtx'][name][0]]
                           for code, name in font.getBestCmap().items()},
        }
    destination.with_suffix('.metrics.zlib').write_bytes(
        zlib.compress(json.dumps(metrics, separators=(',', ':')).encode(), level=9))


if __name__ == '__main__':
    main()
