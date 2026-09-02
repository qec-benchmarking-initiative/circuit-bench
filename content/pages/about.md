---
title: About Circuit Bench
summary: Project goals
---

Papers abound with claims that certain physical circuits are less prone to logical error than others when decoded under various modelling assumptions; likewise papers abound with claims that decoders are more accurate and faster than other decoders.
The maturity of the theory of quantum error correction, together with the open-source Stim format[^stim], now enables us to standardise what constitutes a fault-tolerant quantum circuit under necessarily imperfect, but commonly accepted assumptions.

The purpose of this website is to enable claims of circuit and decoder design to be properly compared and reproduced under transparent and consistent assumptions.
It is a database for Stim circuits and detector error models to be centrally uploaded, stored, and referenced, while allowing for the possibility that other formats may become standard in the future.

Specific versions of decoders, which are encouraged to be provided open-source, can be registered here also; then metrics for the performance of a given decoder on a given circuit can be uploaded to the site, as well as the configuration, training, and hardware required to reproduce the result.
These results can be publicly viewed and referenced in arXiv and journal papers.
For a given circuit, the site will facilitate comparison of decoders' performance on the circuit, broken down by hardware type, decoder capability, or other filters;
the same data enables different circuits to be compared under common decoding assumptions.

## Common benchmarks for decoders

The fundamental challenge in designing a comparison for decoders is the following: by designating a specific and necessarily uniform set of benchmarks, and thereby enabling fair comparison to existing work, one risks preventing decoders from demonstrating their unique strengths.
It also risks falling behind as the circuits the community cares about inevitably change over time.
Demanding a wider suite of tests places more demand on the resources and time of the scientist or developer; updating benchmarks regularly quickly ruins comparisons.

There is no easy solution to these challenges. Nonetheless, it seems likely that Circuit Bench can provide a far better, if necessarily imperfect, approach, vs the *de facto* presently adopted methodology, where
 circuits are chosen for each paper based on some combination of: which circuits are easily accessible; what existing comparisons exist; and which make the decoder under investigation look the best:

1. Members of the community will be able to upload quantum circuits, with light moderation. They will also be able to group these circuits into collections called **benchmarks**.
2. A focused group of QEC researchers, the Circuit Bench steering committee, will work to select and/or develop a handful of **official benchmarks** that reflect the present research interests of the community.
3. It is expected that novel decoders will choose at least one **official benchmark** and run decoding experiments on each constituent circuit, and upload the resulting scores to this website as well as quoting them in the paper. Papers will likely run additional experiments that show the particular strengths of their decoders; these can also be uploaded to the site.
4. The **performance metrics** themselves (what is logical error rate? throughput/latency? what is calibration?) will also be standardised by the steering group of the website.
5. The benchmark choices, the metrics used for comparison, and other scientific definitions used on the site will be subject to regular review in line with community feedback.

## Scientific flexibility vs standardisation

It is difficult to strike a balance between the need to allow for constant innovation and provide some standardisation; nevertheless, we will try:

1. Noise models are collected and referenced in a dedicated database, and a circuit must specify the noise model used to create it. We do not attempt to capture the details of a noise model in the database, instead allowing members of the community to link a paper with a proper description. The steering committee will designate certain noise models as **official** (in particular those used in official benchmarks), with a view to helping with standardisation.
2. Circuits and decoders are categorised by their contributors using systems of tags. Multiple tags may be attached to one circuit or decoder; contributors are encouraged to use **official tags** where applicable but may invent their own and use others designated by the community; over time community tags may be granted **official** status by the steering committee.

See [Tag system](/about/tags/) for the tag families, parent relationships, community tags, and Error Correction Zoo integration.



## Honour system

Benchmarking a decoder is computationally demanding. We rely on the community to upload data about decoder performance honestly; this is already the assumption we rely on for papers.
Nevertheless, Circuit Bench does provide a natural platform for result reproduction: if a decoder is provided open source or is sufficiently well described, reproductions of results will be visible in the same dataset as the originals.

[^stim]: C. Gidney, [*Stim: a fast stabilizer circuit simulator*, Quantum **5**, 497 (2021)](https://doi.org/10.22331/q-2021-07-06-497).
