# Metodología del Sorteo — Futboleros Nube Blanca y Rosal (Honduras)

**Campaña:** Futboleros Nube Blanca y Rosal — Honduras (`futboleros-bn-hn`)
**Premio:** Motocicleta Modelo 2026 — **4 unidades** (2 por ciudad) + **4 suplentes** (2 por ciudad)
**Fecha del sorteo:** 29 de julio de 2026
**Algoritmo:** `python.random.shuffle` v1.0 · Documento reproducible y auditable

---

## Introducción

El sorteo emplea un procedimiento estándar y transparente: en lugar de "sacar
papelitos" a mano, un **generador de números pseudoaleatorios baraja la lista
completa de participantes** y toma los primeros como ganadores. La pieza central
es la **semilla** (*seed*), un número de 128 bits producido con aleatoriedad
criptográfica del sistema operativo en el instante mismo del sorteo. Nadie —ni
siquiera el operador— conoce ni puede predecir la semilla antes de que se genere,
de modo que el resultado es **efectivamente aleatorio e imparcial**: cada
participante del universo tiene exactamente la misma probabilidad de salir
sorteado.

Al mismo tiempo, como el barajado depende **exclusivamente** de esa semilla y de
la lista de participantes, el proceso es **totalmente reproducible**: cualquier
persona que reciba la semilla y la lista puede volver a ejecutar el mismo cálculo
y obtener **exactamente los mismos ganadores**, cuantas veces quiera y en
cualquier computadora. Esta combinación —aleatoriedad genuina en el origen y
determinismo verificable después— es lo que permite **auditar el sorteo sin tener
que confiar en el organizador**: los números hablan por sí solos.

---

## Resumen

El sorteo se ejecutó de forma **determinística y auditable**: una vez fijada una
semilla aleatoria, el resultado queda completamente determinado y cualquier
persona puede reproducirlo y verificarlo. A diferencia de Guatemala (una ronda
por *tienda*), en Honduras se realizó **una ronda por *ciudad*** —agrupando todas
las tiendas de esa ciudad en un solo universo— y, por separado, las **rondas de
suplentes**. Se sortearon **2 titulares y 2 suplentes en cada una de las dos
ciudades** (Tegucigalpa y San Pedro Sula): **8 ganadores** en total repartidos en
**4 rondas**, cada una con su propia semilla y su propia fotografía del universo.

---

## 1. Contexto de la campaña

Al momento del sorteo, la campaña de Honduras había recibido **303 inscripciones**
(**270 válidas**), repartidas en dos ciudades:

| Ciudad | Tiendas | Inscripciones válidas |
|---|---|---:|
| **Tegucigalpa** | Bodega San Juan, El Centavo | 237 |
| **San Pedro Sula** | Bodega M Y M, Bodega Julissy, Surtidora Sampedrana, Surtidora La Confianza, Surtidora La Fe, Abarrotería Doña Irma, Envasadora de Granos Mejía | 33 |

Cada **ciudad** constituye un universo independiente: se sortea por separado, con
su propia semilla, para que el premio de cada ciudad se adjudique únicamente entre
sus participantes.

---

## 2. Depuración del universo: el teléfono compartido `94356059`

Antes del sorteo se detectó que **115 inscripciones** (de ellas
**107 válidas**), **todas registradas en Bodega San Juan (Tegucigalpa)**,
compartían un **único número de teléfono — `94356059`** y **ninguna tenía
correo electrónico**. Bajo ese único número aparecen **82
nombres distintos**: el patrón corresponde a un **registro por lote / por
intermediario** en el punto de venta (un dependiente que inscribió a clientes de
mostrador usando el teléfono de la tienda como marcador de posición), no a una
sola persona.

Por acuerdo con el organizador, **estas inscripciones se excluyeron del universo
de Tegucigalpa**: al compartir un mismo teléfono y carecer de correo, **no es
posible identificarlas ni contactarlas de forma inequívoca** para entregar el
premio y verificar el cumplimiento de sus condiciones. La decisión se aplicó de
forma **objetiva y uniforme** (criterio único: `telefono == 94356059`), sin
selección manual de casos.

**Efecto sobre el universo de Tegucigalpa:** de **237** inscripciones válidas se
pasó a **130** (237 − 107). **San Pedro Sula no se vio afectada** —allí
no existía ese número compartido— y mantuvo sus **33** inscripciones válidas.

> Esta exclusión es el **único** ajuste aplicado al universo. Todo lo demás
> (orden, barajado, selección de ganadores) es puramente mecánico y está fijado
> por la semilla.

---

## 3. Estructura del sorteo

Por cada ciudad se ejecutaron **dos rondas**:

1. **Titulares** — se baraja el universo de la ciudad y se toman los **2 primeros**.
2. **Suplentes** — sobre el universo de la ciudad **menos los 2 titulares ya
   sorteados**, se baraja con una **semilla nueva** y se toman los **2 primeros**.

Así, un titular nunca puede salir además como suplente, y los dos suplentes de una
ciudad son siempre distintos entre sí. En total: **4 rondas**, **8 ganadores**.

---

## 4. Generación de la semilla (*seed*)

- Cada ronda genera su **propia semilla** en el instante de ejecutarse, mediante
  `secrets.token_hex(16)`.
- Son **16 bytes (128 bits) de aleatoriedad criptográfica** tomados directamente
  del sistema operativo (`os.urandom`), representados como **32 caracteres
  hexadecimales**.
- Ningún operador elige ni puede predecir la semilla. Queda **almacenada de forma
  permanente** en el registro del sorteo (campo `seed`), junto con el nombre y la
  versión del algoritmo.

## 5. Construcción del universo de participantes (*pool*)

1. Se toman las inscripciones **válidas** de la campaña, **filtradas por ciudad**
   y, en Tegucigalpa, **excluyendo el teléfono compartido** `94356059`
   (sección 2).
2. El universo se ordena de forma **canónica por `id` ascendente**
   (`order_by('id')`) y se guarda como **fotografía** (`participant_pool_snapshot`):
   la lista exacta que entró al sorteo (ver Anexos).

## 6. Ejecución del algoritmo

1. Se inicializa un generador pseudoaleatorio con la semilla:
   `random.Random(seed)` (Mersenne Twister, MT19937).
2. Se **baraja** el universo con `random.shuffle` (algoritmo Fisher–Yates). Como
   el generador está sembrado con la semilla, **el orden resultante depende al
   100 % de la semilla**: misma semilla + misma lista ⇒ mismo orden, siempre.
3. Los **ganadores** son los **2 primeros** de la lista barajada.
4. Los **suplentes** se sortean en una ronda aparte (premio "— Suplente"), sobre
   el universo restante **después de retirar a los titulares**.

## 7. Reproducibilidad y auditoría

Como se almacenan **semilla + fotografía del universo + algoritmo + versión**, el
sorteo puede volver a ejecutarse y produce **exactamente los mismos ganadores**.
La rutina `verify_raffle_audit` realiza esa comprobación; para **las cuatro
rondas** de Honduras devuelve estado **`ok`** (los ganadores registrados se
reproducen sin diferencias):

| Ronda | Ciudad | Tipo | Universo | Ganadores | Semilla | Verificación |
|---|---|---|---:|---:|---|:--:|
| #13 | Tegucigalpa | Titulares | 130 | 2 | `8a99f964…d9df` | ✅ ok |
| #14 | Tegucigalpa | Suplentes | 128 | 2 | `ff124c05…5dec` | ✅ ok |
| #15 | San Pedro Sula | Titulares | 33 | 2 | `82950512…1a8e` | ✅ ok |
| #16 | San Pedro Sula | Suplentes | 31 | 2 | `62d40fd9…a990` | ✅ ok |

## 8. Resultados

| Ciudad | Tipo | Posición | Ganador | Inscripción (`id`) | Ronda | Semilla |
|---|---|:--:|---|:--:|:--:|---|
| Tegucigalpa | Titular | 1 | Fabiola Rivas | 51 | 13 | `8a99f964…` |
| Tegucigalpa | Titular | 2 | Julio Oseguera | 953 | 13 | `8a99f964…` |
| Tegucigalpa | Suplente | 1 | Bryan noe Arias contreras | 452 | 14 | `ff124c05…` |
| Tegucigalpa | Suplente | 2 | Isua efrain Diaz guzmán | 990 | 14 | `ff124c05…` |
| San Pedro Sula | Titular | 1 | Osman Edgardo enomorado | 1227 | 15 | `82950512…` |
| San Pedro Sula | Titular | 2 | Carlos Pineda | 464 | 15 | `82950512…` |
| San Pedro Sula | Suplente | 1 | Genrry Reyes Morillo reyes | 1082 | 16 | `62d40fd9…` |
| San Pedro Sula | Suplente | 2 | Victor manuel Zapata martinez | 12 | 16 | `62d40fd9…` |

Cada fila conserva el `id` de inscripción, el número de ronda y la semilla, de
modo que **cualquier ganador es rastreable** hasta su sorteo auditable.

---

## 9. Caso detallado: **Fabiola Rivas** (Tegucigalpa, Titular 1)

| Dato | Valor |
|---|---|
| Inscripción (`id`) | **51** |
| Ciudad | Tegucigalpa |
| Ronda | Sorteo Tegucigalpa — Titulares (`Raffle id=13`) |
| Participantes en el universo | **130** (tras excluir el teléfono compartido) |
| Premio | Motocicleta Modelo 2026 (cantidad **2**) |
| Semilla | `8a99f96479dd944f28b067322ff8d9df` |

**Paso a paso:**

1. Su inscripción **51** formaba parte del universo de **130**
   participantes de Tegucigalpa. En la lista ordenada por `id`, ocupaba la
   **posición 4** (índice 3).
2. Se sembró el generador con la semilla de esa ronda y se barajó el universo:
   `random.Random("8a99f96479dd944f28b067322ff8d9df").shuffle(pool)`.
3. Tras el barajado, la inscripción **51 quedó en la primera posición**
   (índice 0). Las cinco primeras posiciones resultaron
   ser: `[51, 953, 164, 1132, 993]`.
4. Como el premio adjudica **2** unidades, los ganadores son los **dos primeros**
   de la lista barajada → **51** (Fabiola Rivas) y
   **953** (Julio Oseguera).
5. La auditoría (`verify_raffle_audit`) reproduce el proceso y confirma este
   resultado exacto: estado **`ok`**.

---

## 10. Cómo reproducir los resultados con la semilla

Reproducir una ronda requiere **solo dos datos**, ambos almacenados de forma
permanente en el registro: **la semilla** (`seed`) y **la fotografía del universo**
(`participant_pool_snapshot`, ver Anexos). Con esos dos valores el barajado y la
selección son **100 % determinísticos**; basta Python 3 (CPython):

```python
import random

# --- Entradas del registro (ejemplo: Sorteo Tegucigalpa — Titulares, Raffle 13) ---
seed = "8a99f96479dd944f28b067322ff8d9df"
pool = [ ... pegar la lista completa del Anexo correspondiente ... ]
cantidad = 2                       # unidades del premio en esta ronda

# --- Reproducción exacta del algoritmo (idéntica a conduct_raffle) ---
rng = random.Random(seed)          # Mersenne Twister (MT19937) sembrado con la semilla
rng.shuffle(pool)                  # barajado Fisher–Yates, determinista dada la semilla

ganadores = pool[:cantidad]        # los primeros N de la lista barajada
print("Ganadores (id de inscripción):", ganadores)
# Salida esperada para la ronda 13: [51, 953]
```

Para relacionar cada `id` con un nombre se consulta la tabla de inscripciones. El
mismo procedimiento reproduce **cualquier** ronda: solo cambian la semilla, la
fotografía del universo y la cantidad del premio (las rondas de **suplentes** usan
su propia semilla y su universo ya sin los titulares).

### Por qué el resultado es siempre idéntico

- `random.Random(seed).shuffle(...)` es **determinista**: la semilla fija por
  completo la secuencia pseudoaleatoria y, por tanto, el orden del barajado.
- El sembrado desde una cadena de texto y el algoritmo de barajado forman parte de
  la **API estable de Python** (CPython 3.x): mismo resultado en cualquier versión
  y sistema operativo.
- Por eso, misma **semilla** + misma **lista** ⇒ mismos **ganadores**, sin
  excepción. El resultado no depende del operador, del hardware ni del momento de
  la verificación.

---

## Anexos — Semillas y fotografías del universo

Cada ronda se reproduce con su semilla y su lista de `id` (ordenada ascendente,
tal como entró al sorteo).

### Anexo A — Ronda #13: Tegucigalpa · Titulares
- **Semilla:** `8a99f96479dd944f28b067322ff8d9df`
- **Premio:** Motocicleta Modelo 2026 (cantidad 2)
- **Universo (130 inscripciones):**

```python
pool = [
    26, 49, 50, 51, 52, 53, 55, 56, 57, 61, 63, 69, 70, 72, 79, 80, 81,
    89, 93, 95, 98, 99, 100, 104, 109, 115, 116, 117, 118, 123, 128, 164, 190, 193,
    194, 218, 219, 220, 221, 249, 262, 264, 265, 271, 272, 273, 276, 281, 303, 316, 332,
    335, 354, 361, 367, 384, 390, 391, 392, 397, 398, 399, 438, 447, 449, 452, 458, 466,
    470, 489, 490, 492, 503, 506, 510, 516, 530, 542, 562, 569, 571, 596, 616, 624, 626,
    636, 665, 678, 712, 720, 735, 741, 743, 804, 821, 826, 830, 831, 832, 842, 856, 857,
    875, 877, 888, 889, 896, 900, 941, 953, 979, 980, 981, 982, 984, 989, 990, 991, 992,
    993, 1002, 1076, 1077, 1078, 1132, 1133, 1189, 1208, 1224, 1226,
]
```

### Anexo B — Ronda #14: Tegucigalpa · Suplentes
- **Semilla:** `ff124c0596aac5ed958709ff783d5dec`
- **Premio:** Motocicleta Modelo 2026 — Suplente (cantidad 2)
- **Universo (128 inscripciones = universo de titulares menos los 2 titulares):**

```python
pool = [
    26, 49, 50, 52, 53, 55, 56, 57, 61, 63, 69, 70, 72, 79, 80, 81, 89,
    93, 95, 98, 99, 100, 104, 109, 115, 116, 117, 118, 123, 128, 164, 190, 193, 194,
    218, 219, 220, 221, 249, 262, 264, 265, 271, 272, 273, 276, 281, 303, 316, 332, 335,
    354, 361, 367, 384, 390, 391, 392, 397, 398, 399, 438, 447, 449, 452, 458, 466, 470,
    489, 490, 492, 503, 506, 510, 516, 530, 542, 562, 569, 571, 596, 616, 624, 626, 636,
    665, 678, 712, 720, 735, 741, 743, 804, 821, 826, 830, 831, 832, 842, 856, 857, 875,
    877, 888, 889, 896, 900, 941, 979, 980, 981, 982, 984, 989, 990, 991, 992, 993, 1002,
    1076, 1077, 1078, 1132, 1133, 1189, 1208, 1224, 1226,
]
```

### Anexo C — Ronda #15: San Pedro Sula · Titulares
- **Semilla:** `82950512f5729e331c7d5eadff6e1a8e`
- **Premio:** Motocicleta Modelo 2026 (cantidad 2)
- **Universo (33 inscripciones):**

```python
pool = [
    6, 12, 20, 62, 464, 815, 816, 823, 837, 838, 839, 858, 863, 864, 871, 969, 970,
    973, 987, 1057, 1067, 1068, 1081, 1082, 1171, 1172, 1173, 1174, 1185, 1186, 1225, 1227, 1228,
]
```

### Anexo D — Ronda #16: San Pedro Sula · Suplentes
- **Semilla:** `62d40fd953535af31fae19b5eddba990`
- **Premio:** Motocicleta Modelo 2026 — Suplente (cantidad 2)
- **Universo (31 inscripciones = universo de titulares menos los 2 titulares):**

```python
pool = [
    6, 12, 20, 62, 815, 816, 823, 837, 838, 839, 858, 863, 864, 871, 969, 970, 973,
    987, 1057, 1067, 1068, 1081, 1082, 1171, 1172, 1173, 1174, 1185, 1186, 1225, 1228,
]
```

---

> Cualquier persona con la fotografía del universo y la semilla —ambas almacenadas
> en el registro de cada sorteo— obtiene los mismos ganadores. El resultado no
> depende del operador ni del momento de ejecución.
