import type { WaterSource } from "../types";

export interface FarmFormValues {
  farmName: string;
  operatorName: string;
  email: string;
  phone: string;
  cropOrLandUse: string;
  waterSource: WaterSource | "";
  consent: boolean;
}

interface FarmProfileFormProps {
  values: FarmFormValues;
  disabled: boolean;
  onChange: (values: FarmFormValues) => void;
}

export function FarmProfileForm({ values, disabled, onChange }: FarmProfileFormProps) {
  function update<K extends keyof FarmFormValues>(key: K, value: FarmFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="farm-profile-form">
      <label className="form-field full-width">
        <span>Farm or property name</span>
        <input
          value={values.farmName}
          maxLength={200}
          placeholder="e.g. Miller Family Farm"
          disabled={disabled}
          required
          onChange={(event) => update("farmName", event.target.value)}
        />
      </label>
      <label className="form-field full-width">
        <span>Your name</span>
        <input
          value={values.operatorName}
          maxLength={120}
          placeholder="Farm owner or operator"
          disabled={disabled}
          required
          onChange={(event) => update("operatorName", event.target.value)}
        />
      </label>
      <label className="form-field full-width">
        <span>Email</span>
        <input
          type="email"
          value={values.email}
          maxLength={254}
          placeholder="you@example.com"
          disabled={disabled}
          required
          onChange={(event) => update("email", event.target.value)}
        />
      </label>
      <label className="form-field full-width">
        <span>Phone <small>optional</small></span>
        <input
          type="tel"
          value={values.phone}
          maxLength={40}
          placeholder="Best number to reach you"
          disabled={disabled}
          onChange={(event) => update("phone", event.target.value)}
        />
      </label>
      <label className="form-field full-width">
        <span>Main crop or land use</span>
        <input
          value={values.cropOrLandUse}
          maxLength={120}
          placeholder="e.g. Corn, alfalfa, grazing"
          disabled={disabled}
          required
          onChange={(event) => update("cropOrLandUse", event.target.value)}
        />
      </label>
      <label className="form-field full-width">
        <span>Main water source</span>
        <select
          value={values.waterSource}
          disabled={disabled}
          required
          onChange={(event) => update("waterSource", event.target.value as WaterSource)}
        >
          <option value="">Choose one</option>
          <option value="groundwater_well">Groundwater well</option>
          <option value="surface_water">Canal, river, or reservoir</option>
          <option value="rainfed">Mostly rainfed</option>
          <option value="municipal">Municipal supply</option>
          <option value="mixed">More than one source</option>
          <option value="unknown">Not sure</option>
          <option value="other">Other</option>
        </select>
      </label>
      <label className="consent-field full-width">
        <input
          type="checkbox"
          checked={values.consent}
          disabled={disabled}
          onChange={(event) => update("consent", event.target.checked)}
        />
        <span>I agree that my farm details and plot boundaries may be saved and used to check whether imagery is available.</span>
      </label>
    </div>
  );
}
