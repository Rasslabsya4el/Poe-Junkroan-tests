// This repo's additions to the generic shapes in ./index.d.ts, by interface merging.
import type { Runs, Machine, Offline } from './index'

declare module './index' {
  interface Split { pob: number }
  interface Fast {
    laptop?: { runs?: Runs; machine?: Machine; error?: string; offline?: Offline }
  }
  interface Reading {
    pobbin_id: string | null
    author_pobbin_id: string | null
  }
  interface BuildData {
    pob_file: string
    pob_file_exists: boolean
    pobbin_id?: string | null
    pobbin_url?: string | null
    author_pobbin_url?: string | null
  }
}
