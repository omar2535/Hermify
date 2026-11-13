{{/* Labels on every object. Selectors use only app/tenant, which never change. */}}
{{- define "hermify.labels" -}}
app.kubernetes.io/part-of: hermify
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{/* Labels on pod templates: no chart version, so a chart release alone doesn't restart pods. */}}
{{- define "hermify.podLabels" -}}
app.kubernetes.io/part-of: hermify
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* storageClassName line for a PVC spec, or nothing for the cluster default. */}}
{{- define "hermify.storageClass" -}}
{{- if .Values.storageClassName }}
storageClassName: {{ .Values.storageClassName }}
{{- end }}
{{- end }}

{{- define "hermify.hindsightUrl" -}}
http://hindsight.{{ .Release.Namespace }}.svc.cluster.local:8888
{{- end }}

{{/* Per-tenant values. Call with (dict "root" $ "t" $tenant). */}}
{{- define "hermify.secretName" -}}
{{- .t.existingSecret | default (printf "hermes-%s-secrets" .t.name) }}
{{- end }}

{{- define "hermify.modelName" -}}
{{- .t.modelName | default (printf "hermes-%s" .t.name) }}
{{- end }}

{{- define "hermify.bankId" -}}
{{- .t.bankId | default (printf "hermes-%s" .t.name) }}
{{- end }}

{{/* Checks that fail the render early, with a readable message. */}}
{{- define "hermify.validate" -}}
{{- $seen := dict }}
{{- range $t := .Values.tenants }}
{{- if not (regexMatch "^[a-z][a-z0-9-]{0,30}[a-z0-9]$|^[a-z]$" (toString $t.name)) }}
{{- fail (printf "tenants: %q is not a valid name (lowercase letters, digits and -, starting with a letter, at most 32)" (toString $t.name)) }}
{{- end }}
{{- if hasKey $seen $t.name }}
{{- fail (printf "tenants: %q is listed twice" $t.name) }}
{{- end }}
{{- $_ := set $seen $t.name true }}
{{- if and $t.bankId (not (regexMatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$" (toString $t.bankId))) }}
{{- fail (printf "tenants[%s].bankId: %q must be letters, digits, '.', '_' or '-'" $t.name (toString $t.bankId)) }}
{{- end }}
{{- $box := $t.box | default dict }}
{{- if and $box.enabled (not $box.authorizedKeys) }}
{{- fail (printf "tenants[%s].box: enabled without authorizedKeys (nobody could log in)" $t.name) }}
{{- end }}
{{- end }}
{{- if and .Values.tenants (or (not .Values.llm.baseUrl) (not .Values.llm.model)) }}
{{- fail "llm.baseUrl and llm.model are required" }}
{{- end }}
{{- with .Values.hindsight.gateway }}
{{- $names := dict }}
{{- range $x := .extraKeys | default list }}
{{- if not (regexMatch "^[a-z][a-z0-9-]{0,40}[a-z0-9]$" (toString $x.name)) }}
{{- fail (printf "hindsight.gateway.extraKeys: name %q must be lowercase letters, digits and -" (toString $x.name)) }}
{{- end }}
{{- if hasKey $names $x.name }}
{{- fail (printf "hindsight.gateway.extraKeys: %q is listed twice" $x.name) }}
{{- end }}
{{- $_ := set $names $x.name true }}
{{- if not (regexMatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$" (toString $x.bank)) }}
{{- fail (printf "hindsight.gateway.extraKeys[%s].bank: %q must be letters, digits, '.', '_' or '-'" $x.name (toString $x.bank)) }}
{{- end }}
{{- if and $x.secretKey (not (regexMatch "^[A-Za-z0-9._-]+$" (toString $x.secretKey))) }}
{{- fail (printf "hindsight.gateway.extraKeys[%s].secretKey: %q isn't a valid Secret key" $x.name (toString $x.secretKey)) }}
{{- end }}
{{- end }}
{{- if and .ingress.enabled (not .enabled) }}
{{- fail "hindsight.gateway.ingress needs hindsight.gateway.enabled: without the gateway it would expose Hindsight's API, which has no per-bank auth" }}
{{- end }}
{{- end }}
{{- if not (regexMatch "^[A-Za-z_][A-Za-z0-9_]*$" .Values.llm.apiKeyEnv) }}
{{- fail "llm.apiKeyEnv must be a valid env var name" }}
{{- end }}
{{- end }}
