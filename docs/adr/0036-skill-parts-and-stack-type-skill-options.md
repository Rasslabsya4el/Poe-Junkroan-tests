# 2026-09-12 D36. Skill parts and stack-type skill options

Status: Accepted

PoB models stacked states as skill parts (Blade Vortex "0 / 5 / 10 Blades",
stages) or numeric skill options (Toxic Rain pods). The pipeline now tries
every part of the main skill right after the skeleton is applied and keeps
the best objective (Blade Vortex 62 -> 987 on a bare rig; Fireball's
"Projectile" and "Explosion" tie); the part name is in the report as an
assumption a player holds on a boss. Toxic Rain pods = the projectile count
(PoB: the maximum is the projectile count; its default of 1 pod is 3x low),
via the rails assumption `toxic_rain_pods_fraction_of_projectiles`. Other
numeric skill options (Intensity, Momentum, Sigil stages) stay at PoB's
defaults until a reference or a measured rule exists.

