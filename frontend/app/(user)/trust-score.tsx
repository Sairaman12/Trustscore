import React, { useState } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as DocumentPicker from 'expo-document-picker';
import { useAuth } from '../../contexts/AuthContext';
import api from '../../utils/api';

const EMPLOYMENT_TYPES = ['Gig Worker', 'Freelancer', 'Content Creator', 'Self-Employed'];
const INCOME_TYPES = ['Daily', 'Weekly', 'Monthly'];

export default function TrustScore() {
  const router = useRouter();
  const { user } = useAuth();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  
  const [formData, setFormData] = useState({
    employment_type: '',
    income_type: '',
    income_amount: '',
    monthly_expenses: '',
    has_previous_loan: false,
  });
  const [bankStatements, setBankStatements] = useState<string[]>([]);

  const updateField = (field: string, value: any) => {
    setFormData({ ...formData, [field]: value });
  };

  const pickBankStatement = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ['image/*', 'application/pdf'],
        multiple: true,
      });

      if (!result.canceled && result.assets) {
        // Convert to base64 with data URL prefix for proper content type detection
        const base64Files: string[] = [];
        for (const asset of result.assets) {
          try {
            const response = await fetch(asset.uri);
            const blob = await response.blob();
            const reader = new FileReader();
            reader.readAsDataURL(blob);
            await new Promise((resolve, reject) => {
              reader.onloadend = () => {
                // Send full data URL (includes content type prefix)
                const base64data = reader.result as string;
                if (base64data) {
                  base64Files.push(base64data);
                }
                resolve(null);
              };
              reader.onerror = reject;
            });
          } catch (err) {
            console.error('Error reading file:', err);
          }
        }
        setBankStatements([...bankStatements, ...base64Files]);
        Alert.alert('Success', `${base64Files.length} document(s) uploaded`);
      }
    } catch (error) {
      console.error('Error picking document:', error);
      Alert.alert('Error', 'Failed to upload documents');
    }
  };

  const handleSubmit = async () => {
    // Validation
    if (!formData.employment_type || !formData.income_type || !formData.income_amount || !formData.monthly_expenses) {
      Alert.alert('Error', 'Please fill all fields');
      return;
    }

    if (bankStatements.length === 0) {
      Alert.alert('Error', 'Please upload at least one bank statement');
      return;
    }

    setLoading(true);
    try {
      await api.post('/api/trust-score/submit', {
        user_id: user?.user_id,
        employment_type: formData.employment_type,
        income_type: formData.income_type,
        income_amount: parseFloat(formData.income_amount),
        monthly_expenses: parseFloat(formData.monthly_expenses),
        has_previous_loan: formData.has_previous_loan,
        bank_statements: bankStatements,
      });

      Alert.alert(
        'Success',
        'Your trust score data has been submitted for review. You will receive your score via WhatsApp once the admin reviews your application.',
        [
          {
            text: 'OK',
            onPress: () => router.replace('/(user)/home'),
          },
        ]
      );
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Failed to submit data');
    } finally {
      setLoading(false);
    }
  };

  const renderStep = () => {
    switch (step) {
      case 1:
        return (
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Employment Type</Text>
            <Text style={styles.stepSubtitle}>Select your employment category</Text>
            
            {EMPLOYMENT_TYPES.map((type) => (
              <TouchableOpacity
                key={type}
                style={[
                  styles.optionButton,
                  formData.employment_type === type && styles.optionButtonSelected,
                ]}
                onPress={() => updateField('employment_type', type)}
              >
                <Text
                  style={[
                    styles.optionButtonText,
                    formData.employment_type === type && styles.optionButtonTextSelected,
                  ]}
                >
                  {type}
                </Text>
                {formData.employment_type === type && (
                  <Ionicons name="checkmark-circle" size={24} color="#6366f1" />
                )}
              </TouchableOpacity>
            ))}

            <TouchableOpacity
              style={[styles.nextButton, !formData.employment_type && styles.nextButtonDisabled]}
              onPress={() => setStep(2)}
              disabled={!formData.employment_type}
            >
              <Text style={styles.nextButtonText}>Next</Text>
            </TouchableOpacity>
          </View>
        );

      case 2:
        return (
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Income Details</Text>
            <Text style={styles.stepSubtitle}>Tell us about your income</Text>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Income Frequency</Text>
              <View style={styles.radioGroup}>
                {INCOME_TYPES.map((type) => (
                  <TouchableOpacity
                    key={type}
                    style={[
                      styles.radioButton,
                      formData.income_type === type && styles.radioButtonSelected,
                    ]}
                    onPress={() => updateField('income_type', type)}
                  >
                    <Text
                      style={[
                        styles.radioButtonText,
                        formData.income_type === type && styles.radioButtonTextSelected,
                      ]}
                    >
                      {type}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Income Amount (₹)</Text>
              <TextInput
                style={styles.input}
                placeholder="Enter amount"
                value={formData.income_amount}
                onChangeText={(value) => updateField('income_amount', value)}
                keyboardType="numeric"
              />
            </View>

            <View style={styles.buttonRow}>
              <TouchableOpacity style={styles.backButton} onPress={() => setStep(1)}>
                <Text style={styles.backButtonText}>Back</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.nextButton, (!formData.income_type || !formData.income_amount) && styles.nextButtonDisabled]}
                onPress={() => setStep(3)}
                disabled={!formData.income_type || !formData.income_amount}
              >
                <Text style={styles.nextButtonText}>Next</Text>
              </TouchableOpacity>
            </View>
          </View>
        );

      case 3:
        return (
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Expenses & Loan History</Text>
            <Text style={styles.stepSubtitle}>Complete your financial profile</Text>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Monthly Expenses (₹)</Text>
              <TextInput
                style={styles.input}
                placeholder="Enter monthly expenses"
                value={formData.monthly_expenses}
                onChangeText={(value) => updateField('monthly_expenses', value)}
                keyboardType="numeric"
              />
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.label}>Previous Loan History</Text>
              <View style={styles.radioGroup}>
                <TouchableOpacity
                  style={[
                    styles.radioButton,
                    formData.has_previous_loan === true && styles.radioButtonSelected,
                  ]}
                  onPress={() => updateField('has_previous_loan', true)}
                >
                  <Text
                    style={[
                      styles.radioButtonText,
                      formData.has_previous_loan === true && styles.radioButtonTextSelected,
                    ]}
                  >
                    Yes
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.radioButton,
                    formData.has_previous_loan === false && styles.radioButtonSelected,
                  ]}
                  onPress={() => updateField('has_previous_loan', false)}
                >
                  <Text
                    style={[
                      styles.radioButtonText,
                      formData.has_previous_loan === false && styles.radioButtonTextSelected,
                    ]}
                  >
                    No
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            <View style={styles.buttonRow}>
              <TouchableOpacity style={styles.backButton} onPress={() => setStep(2)}>
                <Text style={styles.backButtonText}>Back</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.nextButton, !formData.monthly_expenses && styles.nextButtonDisabled]}
                onPress={() => setStep(4)}
                disabled={!formData.monthly_expenses}
              >
                <Text style={styles.nextButtonText}>Next</Text>
              </TouchableOpacity>
            </View>
          </View>
        );

      case 4:
        return (
          <View style={styles.stepContent}>
            <Text style={styles.stepTitle}>Bank Statements</Text>
            <Text style={styles.stepSubtitle}>Upload statements from last 4 months</Text>

            <TouchableOpacity style={styles.uploadCard} onPress={pickBankStatement}>
              <Ionicons name="cloud-upload" size={48} color="#6366f1" />
              <Text style={styles.uploadText}>Upload Bank Statements</Text>
              <Text style={styles.uploadSubtext}>PDF or Images (last 4 months)</Text>
            </TouchableOpacity>

            {bankStatements.length > 0 && (
              <View style={styles.uploadedInfo}>
                <Ionicons name="checkmark-circle" size={24} color="#10b981" />
                <Text style={styles.uploadedText}>
                  {bankStatements.length} document(s) uploaded
                </Text>
              </View>
            )}

            <View style={styles.buttonRow}>
              <TouchableOpacity style={styles.backButton} onPress={() => setStep(3)}>
                <Text style={styles.backButtonText}>Back</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.submitButton, (loading || bankStatements.length === 0) && styles.submitButtonDisabled]}
                onPress={handleSubmit}
                disabled={loading || bankStatements.length === 0}
              >
                {loading ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text style={styles.submitButtonText}>Submit</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        );

      default:
        return null;
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()}>
            <Ionicons name="arrow-back" size={24} color="#1f2937" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Trust Score Assessment</Text>
          <View style={{ width: 24 }} />
        </View>

        {/* Progress Indicator */}
        <View style={styles.progressContainer}>
          {[1, 2, 3, 4].map((item) => (
            <View
              key={item}
              style={[
                styles.progressDot,
                step >= item && styles.progressDotActive,
              ]}
            />
          ))}
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent}>
          {renderStep()}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  keyboardView: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1f2937',
  },
  progressContainer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 20,
  },
  progressDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#e5e7eb',
  },
  progressDotActive: {
    backgroundColor: '#6366f1',
    width: 32,
  },
  scrollContent: {
    flexGrow: 1,
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  stepContent: {
    gap: 20,
  },
  stepTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  stepSubtitle: {
    fontSize: 16,
    color: '#6b7280',
    marginBottom: 8,
  },
  optionButton: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderWidth: 2,
    borderColor: '#e5e7eb',
    borderRadius: 12,
  },
  optionButtonSelected: {
    borderColor: '#6366f1',
    backgroundColor: '#eef2ff',
  },
  optionButtonText: {
    fontSize: 16,
    color: '#6b7280',
    fontWeight: '500',
  },
  optionButtonTextSelected: {
    color: '#6366f1',
    fontWeight: '600',
  },
  inputGroup: {
    gap: 8,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#374151',
  },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  radioGroup: {
    flexDirection: 'row',
    gap: 12,
    flexWrap: 'wrap',
  },
  radioButton: {
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderWidth: 2,
    borderColor: '#e5e7eb',
    borderRadius: 24,
  },
  radioButtonSelected: {
    borderColor: '#6366f1',
    backgroundColor: '#eef2ff',
  },
  radioButtonText: {
    fontSize: 14,
    color: '#6b7280',
    fontWeight: '500',
  },
  radioButtonTextSelected: {
    color: '#6366f1',
    fontWeight: '600',
  },
  uploadCard: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
    borderWidth: 2,
    borderColor: '#6366f1',
    borderStyle: 'dashed',
    borderRadius: 16,
    gap: 12,
  },
  uploadText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6366f1',
  },
  uploadSubtext: {
    fontSize: 14,
    color: '#6b7280',
  },
  uploadedInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 16,
    backgroundColor: '#f0fdf4',
    borderRadius: 12,
  },
  uploadedText: {
    fontSize: 16,
    color: '#10b981',
    fontWeight: '600',
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 8,
  },
  backButton: {
    flex: 1,
    paddingVertical: 16,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#e5e7eb',
    alignItems: 'center',
  },
  backButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#6b7280',
  },
  nextButton: {
    flex: 1,
    backgroundColor: '#6366f1',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  nextButtonDisabled: {
    opacity: 0.5,
  },
  nextButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  submitButton: {
    flex: 1,
    backgroundColor: '#10b981',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  submitButtonDisabled: {
    opacity: 0.5,
  },
  submitButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
});
