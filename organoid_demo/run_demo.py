"""
Run the full vertical slice on the demo corpus.

    python run_demo.py

Pipeline: corpus -> RuleBasedExtractor -> ProtocolStore -> grounded query.
Swap RuleBasedExtractor() for LLMExtractor(complete=...) once a model backend
is wired, and the rest is unchanged.
"""

from corpus import CORPUS
from extractors import RuleBasedExtractor
from store_query import ProtocolStore


def main():
    extractor = RuleBasedExtractor()
    store = ProtocolStore()

    print(f"== Extracting {len(CORPUS)} protocols with {extractor.name} ==\n")
    for entry in CORPUS:
        proto = extractor.extract(entry["doi"], entry["text"], entry.get("organoid_hint"))
        store.add(proto)
        n_factors = len(proto.signaling_factors)
        grounded = sum(1 for r in proto.signaling_factors if r.evidence)
        print(f"  {proto.organoid_type.value:<11} {proto.source_doi:<22} "
              f"{n_factors} signaling factors ({grounded} grounded), "
              f"matrix={proto.matrix.name}, media={proto.base_media}")

    print("\n== Grounded comparison query: signaling factors by organoid type ==\n")
    comp = store.signaling_comparison()
    for otype, data in comp.items():
        print(f"[{otype}]  source: {data['doi']}")
        for f in data["factors"]:
            conc = f" {f['concentration']}" if f["concentration"] else ""
            print(f"    - {f['reagent']} ({f['role']}){conc}")
            if f["citation"]:
                print(f"        grounded: {f['citation']}")
        print()

    # The finding that sounds like research, not a demo:
    print("== Coverage note (this is the error-analysis hook) ==")
    for proto in store.all():
        missing = []
        if proto.matrix.name is None:
            missing.append("matrix")
        if proto.base_media is None:
            missing.append("base_media")
        if not proto.signaling_factors:
            missing.append("signaling_factors")
        status = "complete" if not missing else f"not reported / missed: {', '.join(missing)}"
        print(f"  {proto.organoid_type.value:<11} {status}")


if __name__ == "__main__":
    main()
