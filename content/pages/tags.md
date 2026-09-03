---
title: Tag system and collections
summary: How Circuit Bench classifies and organises circuits and decoders.
---

Circuit Bench (CB) uses tags to categorise circuits and decoders.
There are three tag families: code tags, experiment tags, and decoding-algorithm tags. A circuit may have code and experiment tags; a decoder may have algorithm tags.
Each tag has a page describing the concept and listing scientific references. Parent–child relationships arrange the tags into three generally disconnected directed acyclic graphs, one per family.
The Steering Committee selects official tags. Community members may create tags, describe them, and place them below existing official or community tags.
The Steering Committee will periodically promote community tags to official status to encourage consistent terminology.

## Error Correction Zoo

[The Error Correction Zoo](https://errorcorrectionzoo.org/) (ECZ) already provides a rich taxonomy of error-correcting codes. Circuit Bench makes the ECZ code library available as a special class of code tags.
These tags are synchronised daily from the ECZ. Contributors are encouraged to use them where possible. Contributors may create CB code tags for codes not yet described by the ECZ or when they need finer-grained labels. Where possible, those tags should list an ECZ code tag as a parent.
If a CB tag duplicates an ECZ tag, whether at creation or because the ECZ later introduces a corresponding entry, the Steering Committee can merge the CB tag into the ECZ tag.

## Collections

Circuits may be organised into to collections. Collections are named and curated by the creator of the collection, and may include any public circuit, as well as include sub-collections. A circuit may belong to any number of collections. They may also be tagged with code (including ECZ) and circuit tags.
The intention is simple organisation: a typical use case is to collect all the circuits associated with a given publication, perhaps with sub-collections representing different code distances, with each containing the same circuit at different values of the physical error rate.
Collections, as well as individual circuits, decoders and results, can be made public or private, with their status changed at any time.