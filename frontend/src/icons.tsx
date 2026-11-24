// Component header icon names → icons (SPEC 4 `icon:`), with a fallback per category.

import {
  ChartScatter,
  Code,
  Combine,
  Crop,
  Dices,
  Download,
  Globe,
  Grid3x3,
  Layers,
  Map,
  Pentagon,
  Rows3,
  Sigma,
  SlidersHorizontal,
  Split,
  Table,
  Table2,
  Target,
  TreePine,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";

const BY_NAME: Record<string, LucideIcon> = {
  accuracy: Target,
  align: Combine,
  bands: Layers,
  clip: Crop,
  "confusion-matrix": Table2,
  extract: Table,
  predict: WandSparkles,
  python: Code,
  "random-forest": TreePine,
  "random-sample": Dices,
  "read-raster": Grid3x3,
  "read-vector": Pentagon,
  reclassify: Rows3,
  reproject: Globe,
  split: Split,
  "split-points": Split,
  "stratified-sample": ChartScatter,
  svm: Sigma,
  "write-raster": Download,
  "write-vector": Download,
  "map-viewer": Map,
};

const BY_CATEGORY: Record<string, LucideIcon> = {
  Params: SlidersHorizontal,
  Raster: Grid3x3,
  Vector: Pentagon,
  Sampling: ChartScatter,
  Model: TreePine,
  Validation: Target,
  Script: Code,
};

export function iconFor(name: string | null | undefined, category?: string | null): LucideIcon {
  return (name && BY_NAME[name]) || (category && BY_CATEGORY[category]) || Code;
}
