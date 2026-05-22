import os
import urllib.parse
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent
from mutagen.id3 import ID3, ID3NoHeaderError


def _read_tags(filepath: str) -> dict:
    try:
        tags = ID3(filepath)
    except (ID3NoHeaderError, Exception):
        return {}

    def _text(key):
        f = tags.get(key)
        return str(f.text[0]).strip() if f and hasattr(f, "text") and f.text else ""

    def _txxx(desc):
        f = tags.get(f"TXXX:{desc}")
        return str(f.text[0]).strip() if f and hasattr(f, "text") and f.text else ""

    return {
        "title":        _text("TIT2"),
        "artist":       _text("TPE1"),
        "album":        _text("TALB"),
        "year":         _text("TDRC")[:4],
        "track_number": _text("TRCK").split("/")[0],
        "bpm":          _text("TBPM"),
        "key":          _text("TKEY"),
        "camelot":      _txxx("CAMELOT"),
        "energy":       _txxx("ENERGY"),
        "danceability": _txxx("DANCEABILITY"),
    }


def _scan_library(directory: str) -> list:
    entries = []
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for fname in sorted(files):
            if fname.lower().endswith(".mp3"):
                fpath = os.path.join(root, fname)
                entries.append((fpath, _read_tags(fpath)))
    return entries


def export_rekordbox_xml(directory: str, output_path: str) -> int:
    """Scan directory for MP3s and write a Rekordbox-compatible XML.

    Returns the number of tracks exported.
    """
    entries = _scan_library(directory)
    if not entries:
        return 0

    root_el = Element("DJ_PLAYLISTS", Version="1.0.0")
    SubElement(root_el, "PRODUCT", Name="rekordbox", Version="6.0.0", Company="Pioneer DJ")
    collection = SubElement(root_el, "COLLECTION", Entries=str(len(entries)))

    for i, (fpath, tags) in enumerate(entries, 1):
        name = tags.get("title") or os.path.splitext(os.path.basename(fpath))[0]
        location = "file://" + urllib.parse.quote(os.path.abspath(fpath))
        SubElement(collection, "TRACK", **{
            "TrackID":     str(i),
            "Name":        name,
            "Artist":      tags.get("artist", ""),
            "Album":       tags.get("album", ""),
            "Genre":       "",
            "Kind":        "MP3 File",
            "Size":        str(os.path.getsize(fpath)),
            "TotalTime":   "",
            "DiscNumber":  "0",
            "TrackNumber": tags.get("track_number", "0"),
            "Year":        tags.get("year", ""),
            "BPM":         tags.get("bpm", ""),
            "DateAdded":   "",
            "BitRate":     "",
            "SampleRate":  "",
            "Comments":    f"energy={tags['energy']} dance={tags['danceability']}"
                           if tags.get("energy") else "",
            "PlayCount":   "0",
            "LastPlayed":  "",
            "Rating":      "0",
            "Location":    location,
            "Remixer":     "",
            "Tonality":    tags.get("key", ""),
            "Label":       "",
            "Mix":         "",
        })

    # Flat playlist containing every track
    playlists = SubElement(root_el, "PLAYLISTS")
    root_node = SubElement(playlists, "NODE", Type="0", Name="ROOT", Count="1")
    all_node  = SubElement(root_node, "NODE",
                           Name="All Tracks", Type="1", KeyType="0",
                           Entries=str(len(entries)))
    for i in range(1, len(entries) + 1):
        SubElement(all_node, "TRACK", Key=str(i))

    tree = ElementTree(root_el)
    indent(tree, space="  ")
    with open(output_path, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)

    return len(entries)
